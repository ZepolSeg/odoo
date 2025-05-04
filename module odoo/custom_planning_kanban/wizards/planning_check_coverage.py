# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.tools.safe_eval import safe_eval # For HTML generation security if needed
from collections import defaultdict
from datetime import date, timedelta, datetime, time

class PlanningCoverageCheck(models.TransientModel):
    _name = 'planning.coverage.wizard'
    _description = 'Planning: Check Role Coverage Requirements'

    # --- Default Methods ---
    def _get_default_start_date(self):
        today = fields.Date.context_today(self)
        return today - timedelta(days=today.weekday())

    def _get_default_end_date(self):
        start = self._get_default_start_date()
        return start + timedelta(days=6) # Default to checking current week

    # --- Wizard Fields ---
    date_from = fields.Date("Date From", required=True, default=_get_default_start_date)
    date_to = fields.Date("Date To", required=True, default=_get_default_end_date)
    role_ids = fields.Many2many(
        'planning.role', string="Roles to Check",
        domain="['|', ('min_required_daily', '>', 0), ('max_allowed_daily', '>', 0)]", # Show only roles with limits defined
        help="Leave empty to check all active roles that have coverage limits (Min > 0 or Max > 0).")
    include_drafts = fields.Boolean("Include Draft Shifts", default=False,
                                  help="If checked, considers assigned draft shifts in the coverage count (otherwise only counts published shifts).")
    result_display = fields.Html("Results", compute="_compute_coverage_results", readonly=True, sanitize=False) # Ensure generated HTML is safe


    # --- Constraints ---
    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValidationError(_("The 'Date From' cannot be later than the 'Date To'."))


    # --- Compute Method ---
    @api.depends('date_from', 'date_to', 'role_ids', 'include_drafts')
    def _compute_coverage_results(self):
        """Compute and generate HTML report for role coverage."""
        if not self.date_from or not self.date_to:
            self.result_display = "<p class='text-warning'>Please select a valid date range.</p>"
            return

        Role = self.env['planning.role']
        Slot = self.env['planning.slot']

        # 1. Determine which roles to analyze
        role_criteria = [('active', '=', True)] # Always check active roles
        # Base limits domain: Must have Min or Max > 0 defined
        limits_domain = ['|', ('min_required_daily', '>', 0), ('max_allowed_daily', '>', 0)]
        if self.role_ids: # If user selected specific roles, check only those WITH limits
             role_criteria.extend([('id', 'in', self.role_ids.ids)] + limits_domain)
        else: # If no roles selected, check ALL active roles WITH limits
            role_criteria.extend(limits_domain)

        roles_to_check = Role.search_read(role_criteria, ['id', 'display_name', 'min_required_daily', 'max_allowed_daily'])
        if not roles_to_check:
             self.result_display = "<p class='text-info'>No active roles found with coverage limits defined that match your filter.</p>"
             return
        role_limits_map = {r['id']: r for r in roles_to_check}


        # 2. Fetch relevant planning slots
        period_start_dt = datetime.combine(self.date_from, time.min)
        period_end_dt = datetime.combine(self.date_to, time.max)
        slot_states = ['published']
        if self.include_drafts: slot_states.append('draft')

        slot_domain = [
            ('start_datetime', '<=', period_end_dt), # Slot overlaps with period
            ('end_datetime', '>=', period_start_dt),
            ('state', 'in', slot_states),
            ('active', '=', True),
            ('employee_id', '!=', False), # Must have an employee
            ('role_id', 'in', list(role_limits_map.keys())), # Only roles we're checking
        ]
        # Using search_read for efficiency
        relevant_slots = Slot.search_read(
            slot_domain, ['id', 'start_datetime', 'end_datetime', 'role_id', 'employee_id']
            )

        # 3. Aggregate coverage (unique employees per role per day)
        daily_coverage = defaultdict(lambda: defaultdict(set)) # {date: {role_id: {emp_id, ...}}}
        if relevant_slots:
            # Iterate through each day in the selected period
            current_date = self.date_from
            while current_date <= self.date_to:
                day_start_dt = datetime.combine(current_date, time.min)
                day_end_dt = datetime.combine(current_date, time.max)
                # Find slots overlapping with *this specific day*
                for slot in relevant_slots:
                    if slot['start_datetime'] < day_end_dt and slot['end_datetime'] > day_start_dt:
                         role_id = slot['role_id'][0] # role_id is (id, name) tuple
                         emp_id = slot['employee_id'][0]
                         daily_coverage[current_date][role_id].add(emp_id)
                current_date += timedelta(days=1)


        # 4. Build HTML output
        html_rows = []
        overall_status = 'success' # Assume success initially
        dates_in_period = [self.date_from + timedelta(days=x) for x in range((self.date_to - self.date_from).days + 1)]

        for day in dates_in_period:
            day_coverage = daily_coverage.get(day, {})
            day_has_issues = False

            # Check coverage for roles we expected to monitor
            for role_id, role_data in sorted(role_limits_map.items(), key=lambda item: item[1]['display_name']):
                employee_set = day_coverage.get(role_id, set())
                count = len(employee_set)
                min_req = role_data['min_required_daily']
                max_allow = role_data['max_allowed_daily']
                status = 'ok'
                status_class = 'text-success'
                status_icon = 'fa-check-circle' # Font Awesome icon

                if min_req > 0 and count < min_req:
                     status = 'under'
                     status_class = 'text-danger'
                     status_icon = 'fa-exclamation-triangle'
                     day_has_issues = True
                     if overall_status != 'danger': overall_status = 'warning'
                elif max_allow > 0 and count > max_allow:
                    status = 'over'
                    status_class = 'text-warning'
                    status_icon = 'fa-arrow-circle-up'
                    day_has_issues = True
                    if overall_status != 'danger': overall_status = 'warning' # Over is a warning

                if status != 'ok' or min_req > 0 or max_allow > 0 : # Only show roles with limits or issues
                     row = f"""
                     <tr class="{ 'table-danger' if status=='under' else 'table-warning' if status=='over' else '' }">
                        <td>{day.strftime('%Y-%m-%d (%a)')}</td>
                        <td>{role_data['display_name']}</td>
                        <td class='text-center'>{count}</td>
                        <td class='text-center'>{min_req if min_req > 0 else '-'}</td>
                        <td class='text-center'>{max_allow if max_allow > 0 else '-'}</td>
                        <td class='text-center {status_class}'><i class='fa {status_icon} mr-1'></i> {status.capitalize()}</td>
                     </tr>
                     """
                     html_rows.append(row)

        if not html_rows:
             summary = "<div class='alert alert-info mt-3' role='alert'>No coverage data to display. Either no shifts were found for roles with limits, or no limits are defined for the selected roles/period.</div>"
             self.result_display = summary
        else:
             table_header = """
             <table class='table table-sm table-striped table-hover mt-3'>
                <thead class='thead-light'>
                    <tr><th>Date</th><th>Role</th><th class='text-center'>Actual</th><th class='text-center'>Min Req.</th><th class='text-center'>Max Allow.</th><th class='text-center'>Status</th></tr>
                </thead>
                <tbody>
             """
             table_footer = "</tbody></table>"
             if overall_status == 'success':
                 summary = "<div class='alert alert-success mt-3' role='alert'><i class='fa fa-check-circle'></i> Coverage meets all defined requirements.</div>"
             else:
                 summary = "<div class='alert alert-warning mt-3' role='alert'><i class='fa fa-exclamation-triangle'></i> Coverage issues detected (see details below).</div>"

             self.result_display = summary + table_header + "".join(html_rows) + table_footer