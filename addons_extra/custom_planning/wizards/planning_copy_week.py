# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import timedelta, datetime, time

class PlanningCopyWeek(models.TransientModel):
    _name = 'planning.copy.wizard'
    _description = 'Planning: Copy Week Wizard'

    # --- Default Methods ---
    def _get_default_start_date(self):
        """Monday of the current week."""
        today = fields.Date.context_today(self)
        return today - timedelta(days=today.weekday())

    def _get_default_target_date(self):
        """Monday of the next week."""
        return self._get_default_start_date() + timedelta(weeks=1)

    # --- Wizard Fields ---
    source_date_start = fields.Date(
        "Copy From Week Starting On", required=True, default=_get_default_start_date,
        help="Select the Monday of the week you want to copy FROM."
        )
    target_date_start = fields.Date(
        "Paste To Week Starting On", required=True, default=_get_default_target_date,
        help="Select the Monday of the week you want to copy TO."
        )
    employee_ids = fields.Many2many(
        'hr.employee', string="Filter Employees",
        help="Optional: Only copy shifts for these selected employees. Leave empty for all.")
    role_ids = fields.Many2many(
        'planning.role', string="Filter Roles",
        help="Optional: Only copy shifts with these selected roles. Leave empty for all.")
    copy_assignments = fields.Boolean(
        "Copy Employee Assignments", default=True,
        help="If checked, the copied shifts will be assigned to the same employee. If unchecked, they will be unassigned.")
    state_filter = fields.Selection([
        ('all_but_cancelled', 'All except Cancelled'),
        ('published', 'Published only'),
        ('draft_published', 'Draft & Published'),
        ('draft', 'Draft only'),
        ], string="Copy Shifts With State", default='draft_published', required=True,
           help="Select the state(s) of the shifts you want to copy.")
    target_state = fields.Selection([
        ('keep', 'Keep Original State'),
        ('draft', 'Set all to Draft'),
        ('published', 'Attempt to Set all to Published (will skip if conflicts found)')
        ], string="Set State of Copied Shifts", default='draft', required=True,
           help="Choose the state for the newly created shifts.")


    # --- Constraints ---
    @api.constrains('source_date_start', 'target_date_start')
    def _check_dates(self):
        """Prevent target week from being before or same as source week."""
        for wizard in self:
            if wizard.source_date_start and wizard.target_date_start and wizard.source_date_start >= wizard.target_date_start:
                raise UserError(_("Target week must start after the source week."))


    # --- Action Button ---
    def action_copy_week(self):
        """Main logic to copy planning slots."""
        self.ensure_one()
        Slot = self.env['planning.slot'] # Use context user's permissions

        # Calculate date ranges (as timezone naive datetimes for reliable comparison)
        source_start_dt = datetime.combine(self.source_date_start, time.min)
        source_end_dt = source_start_dt + timedelta(days=7)
        target_start_dt = datetime.combine(self.target_date_start, time.min)
        delta = target_start_dt - source_start_dt # Time difference to add

        # Build domain for source slots
        source_domain = [
            ('start_datetime', '>=', source_start_dt),
            ('start_datetime', '<', source_end_dt),
            ('active', '=', True), # Usually copy active slots only
        ]
        if self.employee_ids: source_domain.append(('employee_id', 'in', self.employee_ids.ids))
        if self.role_ids: source_domain.append(('role_id', 'in', self.role_ids.ids))

        states_map = {
            'draft': ['draft'], 'published': ['published'],
            'draft_published': ['draft', 'published'],
            'all_but_cancelled': ['draft', 'published'], # Exclude 'cancelled'
        }
        source_domain.append(('state', 'in', states_map.get(self.state_filter, ['draft', 'published'])))

        slots_to_copy = Slot.search(source_domain)

        if not slots_to_copy:
            raise UserError(_("No planning shifts found matching your criteria in the source week."))

        # Prepare values for creation, performing pre-checks
        vals_list = []
        skipped_count = 0
        processed_count = 0
        for slot in slots_to_copy:
            processed_count += 1
            target_start = slot.start_datetime + delta
            target_end = slot.end_datetime + delta
            target_employee_id = slot.employee_id.id if self.copy_assignments else False

            if self.target_state == 'keep':
                final_target_state = slot.state
                if final_target_state == 'cancelled': # Never copy as cancelled
                    final_target_state = 'draft'
            else:
                final_target_state = self.target_state # draft or published

            # Pre-flight Check: If trying to publish, check for conflicts/leaves IN THE TARGET WEEK
            if final_target_state == 'published' and target_employee_id:
                # Check conflicts with existing slots in target week
                if Slot.search_count([
                    ('employee_id', '=', target_employee_id), ('state', '=', 'published'),
                    ('active', '=', True), ('start_datetime', '<', target_end),
                    ('end_datetime', '>', target_start),
                    ]):
                     _logger.info("Skipping copy of slot %d to target week: Conflict with existing shifts for employee %s.", slot.id, slot.employee_id.name)
                     skipped_count += 1
                     continue # Skip this slot

                 # Check leaves in target week
                if self.env['hr.leave'].search_count([
                    ('employee_id', '=', target_employee_id), ('state', '=', 'validate'),
                    ('date_from', '<', target_end), ('date_to', '>', target_start),
                    ]):
                    _logger.info("Skipping copy of slot %d to target week: Validated time off for employee %s.", slot.id, slot.employee_id.name)
                    skipped_count += 1
                    continue # Skip this slot

            # If all checks pass (or not publishing), prepare values
            vals_list.append({
                 'start_datetime': target_start, 'end_datetime': target_end,
                 'state': final_target_state,
                 'employee_id': target_employee_id,
                 'role_id': slot.role_id.id,
                 'notes': slot.notes, 'company_id': slot.company_id.id,
                 'active': True,
                 'rrule': False, 'recurrence_id': False, # Never copy recurrence links
            })

        # Final check if anything is left to create
        if not vals_list:
             if skipped_count > 0:
                 raise UserError(_("No shifts were copied. %d shifts were skipped due to potential conflicts or time off in the target week.", skipped_count))
             else: # Should not happen if slots_to_copy was found, but safeguard
                 raise UserError(_("No shifts were prepared for copying."))

        # Create slots in batch
        try:
            created_slots = Slot.create(vals_list)
        except (ValidationError, UserError) as e:
            # Catch validation errors that might occur despite pre-flight checks (e.g., batch conflicts)
             _logger.error("Validation Error during batch creation of copied shifts: %s", e, exc_info=True)
             raise UserError(_("Failed to create copied shifts due to a validation error: %s", e))
        except Exception as e:
            _logger.error("Unexpected Error during batch creation of copied shifts: %s", e, exc_info=True)
            raise UserError(_("An unexpected error occurred: %s", e))

        # Success message and action to show results
        _logger.info("Copied %d shifts from week %s to week %s. Skipped %d.",
                     len(created_slots), self.source_date_start, self.target_date_start, skipped_count)

        # Return action to display the created slots
        return {
            'name': _("Copied Shifts - Week of %s", self.target_date_start.strftime('%d %b %Y')),
            'type': 'ir.actions.act_window',
            'res_model': 'planning.slot',
            'view_mode': 'gantt,tree,form', # Show in Gantt first
            'domain': [('id', 'in', created_slots.ids)],
             'context': { # Help Gantt focus on the target week
                'default_start_datetime': datetime.combine(self.target_date_start, time(8,0)), # Focus Gantt view
                'initialDate': self.target_date_start,
            },
            'target': 'current',
        }