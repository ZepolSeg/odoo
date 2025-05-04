# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError # Assurez-vous que ceci est importé
from collections import defaultdict
from datetime import date, timedelta, datetime, time
import logging # Optionnel mais utile

_logger = logging.getLogger(__name__) # Optionnel

class PlanningCoverageCheck(models.TransientModel):
    _name = 'planning.coverage.wizard'
    _description = 'Planning: Role Coverage Check'

    def _default_start_date(self):
        today = fields.Date.context_today(self)
        return today - timedelta(days=today.weekday())

    def _default_end_date(self):
        start = self._default_start_date()
        return start + timedelta(days=6)

    date_from = fields.Date("Date From", required=True, default=_default_start_date)
    date_to = fields.Date("Date To", required=True, default=_default_end_date)
    role_ids = fields.Many2many('planning.role', string="Roles to Check", help="Leave empty to check all roles with Min/Max defined.")
    include_drafts = fields.Boolean("Include Draft Shifts", help="Check coverage including assigned draft shifts.")

    # ---> VÉRIFIEZ CETTE DÉFINITION DE CHAMP <---
    result_lines = fields.Html(
        "Results",
        compute="_compute_results",
        readonly=True,
        sanitize=False # Attention avec sanitize=False
    )

    @api.constrains('date_from', 'date_to')
    def _check_date_range(self):
        for wizard in self: # Itérer sur self
            if wizard.date_from and wizard.date_to and wizard.date_from > wizard.date_to:
                raise ValidationError(_("Date From cannot be after Date To."))

    # Important: La méthode compute doit itérer sur self
    @api.depends('date_from', 'date_to', 'role_ids', 'include_drafts')
    def _compute_results(self):
        """ Calculates the coverage per role and per day """
        for wizard in self: # Itérer sur self est crucial pour les compute
            if not wizard.date_from or not wizard.date_to:
                wizard.result_lines = _("<p>Please select a valid date range.</p>")
                continue # Passer au wizard suivant si self contient plusieurs enregistrements

            # ... (logique de calcul comme fournie précédemment) ...
            # Assurez-vous que la logique est à l'intérieur de la boucle for wizard in self:

            # --- Exemple de la fin de la logique ---
            role_domain = [('active', '=', True)]
            sub_domain = ['|', ('min_required_daily', '>', 0), ('max_allowed_daily', '>', 0)]
            if wizard.role_ids:
                 role_domain.extend([('id', 'in', wizard.role_ids.ids)] + sub_domain)
            else:
                 role_domain.extend(sub_domain)
            roles = self.env['planning.role'].search_read(role_domain, ['id', 'name', 'min_required_daily', 'max_allowed_daily'])
            if not roles:
                wizard.result_lines = _("<p>No active roles found with coverage limits defined (or matching your filter).</p>")
                continue
            role_limits = {r['id']: {'name': r['name'], 'min': r['min_required_daily'], 'max': r['max_allowed_daily']} for r in roles}

            start_dt = datetime.combine(wizard.date_from, time.min)
            end_dt = datetime.combine(wizard.date_to, time.max)

            slot_states = ['published']
            if wizard.include_drafts: slot_states.append('draft')
            slot_domain = [
                 ('start_datetime', '<=', end_dt), ('end_datetime', '>=', start_dt),
                 ('state', 'in', slot_states), ('active', '=', True),
                 ('employee_id', '!=', False), ('role_id', 'in', list(role_limits.keys()))
            ]
            slots = self.env['planning.slot'].search_read(
                 slot_domain, ['id', 'start_datetime', 'end_datetime', 'role_id', 'employee_id']
            )

            daily_coverage = defaultdict(lambda: defaultdict(set))
            if slots:
                current_date = wizard.date_from
                while current_date <= wizard.date_to:
                    day_start_dt = datetime.combine(current_date, time.min)
                    day_end_dt = datetime.combine(current_date, time.max)
                    for slot in slots:
                        if slot['start_datetime'] < day_end_dt and slot['end_datetime'] > day_start_dt:
                            role_id = slot['role_id'][0]
                            employee_id = slot['employee_id'][0]
                            daily_coverage[current_date][role_id].add(employee_id)
                    current_date += timedelta(days=1)

            html = "<div class='table-responsive'><table class='table table-sm table-hover table-bordered'>"
            html += "<thead class='thead-light'><tr><th>Date</th><th>Role</th><th class='text-center'>Coverage</th><th class='text-center'>Min Req.</th><th class='text-center'>Max Allow.</th><th class='text-center'>Status</th></tr></thead><tbody>"

            has_issues = False
            rows_added = 0
            all_checked_dates = set(wizard.date_from + timedelta(days=x) for x in range((wizard.date_to - wizard.date_from).days + 1))
            processed_dates = set(daily_coverage.keys()) # Dates with actual slots

            # Iterate through days with slots first
            for day in sorted(list(processed_dates)):
                day_str = day.strftime('%Y-%m-%d (%a)')
                day_roles = daily_coverage[day]
                sorted_role_ids = sorted(day_roles.keys(), key=lambda r_id: role_limits.get(r_id, {}).get('name', ''))

                for role_id in sorted_role_ids:
                    # ... (logic to build row for existing role coverage) ...
                    role_info = role_limits[role_id]
                    count = len(day_roles[role_id])
                    min_req = role_info['min']
                    max_allow = role_info['max']
                    status_msg = "OK"
                    status_class = "badge badge-success"
                    issue = False
                    if min_req > 0 and count < min_req:
                        status_msg = f"UNDER ({count} / {min_req})"
                        status_class = "badge badge-danger"; issue = True
                    elif max_allow > 0 and count > max_allow:
                        status_msg = f"OVER ({count} / {max_allow})"
                        status_class = "badge badge-warning"; issue = True
                    has_issues |= issue
                    html += f"<tr><td>{day_str}</td><td>{role_info['name']}</td><td class='text-center'>{count}</td><td class='text-center'>{min_req if min_req > 0 else '-'}</td><td class='text-center'>{max_allow if max_allow > 0 else '-'}</td><td class='text-center'><span class='{status_class}'>{status_msg}</span></td></tr>"
                    rows_added += 1

                # Check for missing roles on this day (that have min req > 0)
                missing_roles_on_day = set(r_id for r_id, limits in role_limits.items() if limits['min'] > 0) - set(day_roles.keys())
                for role_id in sorted(list(missing_roles_on_day), key=lambda r_id: role_limits.get(r_id, {}).get('name', '')):
                    # ... (logic to build row for missing role) ...
                     role_info = role_limits[role_id]
                     status_msg = f"MISSING (0 / {role_info['min']})"
                     html += f"<tr class='table-danger'><td>{day_str}</td><td>{role_info['name']}</td><td class='text-center'>0</td><td class='text-center'>{role_info['min']}</td><td class='text-center'>{role_info.get('max', '-') if role_info.get('max', 0) > 0 else '-'}</td><td class='text-center'><span class='badge badge-danger'>{status_msg}</span></td></tr>"
                     rows_added += 1; has_issues = True

            # Check dates without any slots for roles with min reqs
            dates_without_slots = sorted(list(all_checked_dates - processed_dates))
            missing_roles_min_req = sorted([r_id for r_id, limits in role_limits.items() if limits['min'] > 0], key=lambda r_id: role_limits.get(r_id, {}).get('name', ''))
            for day in dates_without_slots:
                 day_str = day.strftime('%Y-%m-%d (%a)')
                 for role_id in missing_roles_min_req:
                     # ... (logic to build row for missing role on empty day) ...
                     role_info = role_limits[role_id]
                     status_msg = f"MISSING (0 / {role_info['min']})"
                     html += f"<tr class='table-danger'><td>{day_str}</td><td>{role_info['name']}</td><td class='text-center'>0</td><td class='text-center'>{role_info['min']}</td><td class='text-center'>{role_info.get('max', '-') if role_info.get('max', 0) > 0 else '-'}</td><td class='text-center'><span class='badge badge-danger'>{status_msg}</span></td></tr>"
                     rows_added += 1; has_issues = True

            html += "</tbody></table></div>"

            if rows_added == 0:
                 result_message = _("<div class='alert alert-warning mt-2' role='alert'>No relevant shifts found matching criteria for the selected roles/period.</div>")
            elif not has_issues:
                result_message = _("<div class='alert alert-success mt-2' role='alert'>Coverage meets all defined requirements for the selected period and roles.</div>")
            else:
                 result_message = _("<div class='alert alert-danger mt-2' role='alert'>Coverage issues detected (understaffed or overstaffed roles/days).</div>")

            # Assigner le résultat au champ du wizard courant dans la boucle
            wizard.result_lines = result_message + html