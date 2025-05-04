# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from dateutil.relativedelta import relativedelta
from dateutil import rrule
from dateutil.parser import parse
import pytz
from datetime import datetime, time, timedelta
from collections import defaultdict
import logging

_logger = logging.getLogger(__name__)

class PlanningSlot(models.Model):
    _name = 'planning.slot'
    _description = 'Planning Shift / Slot'
    _order = 'start_datetime, id'
    _inherit = ['mail.thread', 'mail.activity.mixin'] # For communication history

    # --- Core Fields ---
    name = fields.Char("Description", compute='_compute_display_name', store=True, readonly=False)
    active = fields.Boolean(default=True, tracking=True, index=True,
                            help="If unchecked, the planning slot is hidden.")
    employee_id = fields.Many2one(
        comodel_name='hr.employee', string="Employee", tracking=True, copy=False, index=True
    )
    role_id = fields.Many2one(
        comodel_name='planning.role', string="Required Role", tracking=True, index=True
    )
    start_datetime = fields.Datetime("Start DateTime", required=True, index=True, tracking=True)
    end_datetime = fields.Datetime("End DateTime", required=True, index=True, tracking=True)
    duration = fields.Float("Duration (Hours)", compute='_compute_duration', store=True, help="Duration in hours.")
    # allocation_percentage = fields.Float("Allocation (%)", default=100.0, tracking=True, help="Employee allocation percentage for this slot if concurrent work is allowed.")
    color = fields.Integer("Color Index", related='role_id.color', readonly=True) # For UI consistency
    notes = fields.Text("Internal Notes", help="Additional information for planners or the employee.")
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('cancelled', 'Cancelled'),
        ], string='Status', default='draft', required=True, copy=False, tracking=True, index=True,
           help="Draft: Not confirmed\nPublished: Confirmed and visible\nCancelled: No longer valid")

    # --- Recurrence Fields ---
    rrule = fields.Char('Recurrence Rule (RRULE)', copy=False, help="iCalendar RRULE string. Defines repetition. Leave empty for non-recurring slots.")
    recurrence_id = fields.Many2one(
        comodel_name='planning.slot', string="Recurrence Base", index=True, ondelete='cascade', readonly=True, copy=False,
        help="The original slot this occurrence was generated from."
        )
    # Note: Advanced recurrence exceptions are not handled in this version.

    # --- Computed Fields for Live Status ---
    # These are not stored for real-time feel but are costly.
    # Consider stored fields updated by cron for better performance on large scale.
    attendance_state = fields.Selection([
            ('present', 'Present'), ('absent', 'Absent'), ('late', 'Late'),
            ('early_out', 'Early Out'), ('leave', 'Time Off'), ('scheduled', 'Scheduled'),
            ('off', 'Off / Cancelled'), ('conflicting', 'Conflict')
        ], string="Live Status", compute='_compute_live_status', store=False,
           help="Indicates the current state based on Time Off, other shifts, and attendance (if applicable and recent).")
    has_conflict = fields.Boolean("Has Conflict", compute='_compute_live_status', store=False,
                                 help="Technical field indicating an overlap with another published shift.")

    # --- Compute & Search Methods ---
    @api.depends('start_datetime', 'end_datetime')
    def _compute_duration(self):
        """Calculate slot duration in hours."""
        for slot in self:
            if slot.start_datetime and slot.end_datetime:
                delta = slot.end_datetime - slot.start_datetime
                slot.duration = delta.total_seconds() / 3600.0
            else:
                slot.duration = 0.0

    @api.depends('employee_id.name', 'role_id.name', 'start_datetime')
    def _compute_display_name(self):
        """Generate a user-friendly name for the slot."""
        for slot in self:
            parts = [slot.role_id.name, slot.employee_id.name]
            slot.name = " - ".join(filter(None, parts)) or _("Slot @ %s") % fields.Datetime.context_timestamp(slot, slot.start_datetime).time() if slot.start_datetime else _("New Slot")

    @api.depends('employee_id', 'start_datetime', 'end_datetime', 'state', 'active')
    def _compute_live_status(self):
        """Compute 'live' status (time off, conflict, basic attendance). Non-stored, performance impact."""
        # Quickly handle inactive/unassigned slots
        for slot in self:
            if not slot.active or slot.state == 'cancelled':
                slot.attendance_state = 'off'
                slot.has_conflict = False
            elif not slot.employee_id or not slot.start_datetime or not slot.end_datetime:
                 slot.attendance_state = 'scheduled' # Or unassigned?
                 slot.has_conflict = False
            else:
                 # Placeholder, actual calculation needs data fetching
                 slot.attendance_state = 'scheduled'
                 slot.has_conflict = False # Default to no conflict

        slots_to_process = self.filtered(lambda s: s.active and s.state != 'cancelled' and s.employee_id and s.start_datetime and s.end_datetime)
        if not slots_to_process:
            return

        # Data pre-fetching (consider limiting range or optimizing further)
        now = fields.Datetime.now() # UTC Now
        employee_ids = slots_to_process.mapped('employee_id.id')
        min_dt = min(slots_to_process.mapped('start_datetime')) - timedelta(days=1)
        max_dt = max(slots_to_process.mapped('end_datetime')) + timedelta(days=1)

        leave_map = self._fetch_employee_intervals(
            'hr.leave', employee_ids, min_dt, max_dt,
            [('state', '=', 'validate')] # Only approved time off
        )
        conflict_map = self._fetch_employee_intervals(
            'planning.slot', employee_ids, min_dt, max_dt,
            [('state', '=', 'published'), ('active', '=', True)] # Only published shifts for conflicts
        )
        # Fetch LAST attendance record per relevant employee
        # hr.attendance required a different strategy than intervals
        attendance_map = self._fetch_last_attendances(employee_ids)


        # Process each relevant slot
        for slot in slots_to_process:
            start_utc = slot.start_datetime
            end_utc = slot.end_datetime
            emp_id = slot.employee_id.id
            live_state = 'scheduled' # Default assume future/unknown
            conflict_flag = False

            # 1. Check Time Off (priority)
            if any(leave_start < end_utc and leave_end > start_utc
                   for leave_start, leave_end in leave_map.get(emp_id, [])):
                live_state = 'leave'
                conflict_flag = False # If on time off, overlaps are irrelevant
            else:
                 # 2. Check Shift Conflicts (only if published)
                if slot.state == 'published':
                    if any(conflict_id != slot.id and c_start < end_utc and c_end > start_utc
                           for conflict_id, c_start, c_end in conflict_map.get(emp_id, [])):
                        conflict_flag = True
                        # Report conflict but check attendance too

                # 3. Check Last Attendance (Basic - Needs refinement for accuracy)
                last_att = attendance_map.get(emp_id)
                att_state = 'scheduled' if start_utc > now else 'absent' # Assume absent if past w/o record

                if last_att:
                    check_in = last_att['check_in']
                    check_out = last_att['check_out']
                    att_overlaps = check_in < end_utc and (not check_out or check_out > start_utc)

                    if att_overlaps:
                         if not check_out: # Currently Checked IN during the slot time
                             att_state = 'late' if check_in > start_utc else 'present'
                         else: # Checked OUT, but overlap occurred
                            if check_out < end_utc: att_state = 'early_out'
                            elif check_in > start_utc: att_state = 'late'
                            else: att_state = 'present' # Attended the slot duration

                    # Note: This doesn't handle multiple check-ins/outs during the slot perfectly.

                # Determine final state, Conflict visually overrides attendance status if present
                live_state = att_state if not conflict_flag else 'conflicting'

            slot.attendance_state = live_state
            slot.has_conflict = conflict_flag


    def _fetch_employee_intervals(self, model_name, employee_ids, date_from, date_to, domain):
        """ Fetches date intervals (start/end) for given employees, grouped by employee ID."""
        Model = self.env[model_name]
        # Determine date field names based on model
        if hasattr(Model, 'start_datetime'):
             date_from_field, date_to_field = 'start_datetime', 'end_datetime'
        elif hasattr(Model, 'date_from'):
            date_from_field, date_to_field = 'date_from', 'date_to'
        else:
             _logger.warning("Model %s does not have standard date fields for interval fetching.", model_name)
             return {}

        full_domain = domain + [
            ('employee_id', 'in', employee_ids),
            (date_from_field, '<=', date_to), # Interval overlap
            (date_to_field, '>=', date_from),
        ]
        records = Model.search_read(full_domain, ['id', 'employee_id', date_from_field, date_to_field])
        grouped_data = defaultdict(list)
        for rec in records:
            emp_id = rec['employee_id'][0]
            interval_id = rec['id'] if model_name == 'planning.slot' else None # Need ID for self-check in conflicts
            grouped_data[emp_id].append((interval_id, rec[date_from_field], rec[date_to_field]))
        return grouped_data

    def _fetch_last_attendances(self, employee_ids):
        """ Fetches the very last attendance record for each employee ID """
        if not employee_ids: return {}
        # Optimize query to get only latest per employee using window functions or subqueries if needed.
        # Basic approach (less performant for many employees/attendances):
        attendances = self.env['hr.attendance'].search_read(
            [('employee_id', 'in', employee_ids)],
            ['employee_id', 'check_in', 'check_out'],
            order='check_in DESC'
        )
        last_attendance_map = {}
        for att in attendances:
            emp_id = att['employee_id'][0]
            if emp_id not in last_attendance_map:
                last_attendance_map[emp_id] = att
        return last_attendance_map


    # --- Constraints ---
    @api.constrains('start_datetime', 'end_datetime')
    def _check_dates_ordered(self):
        """Ensure start date is before end date."""
        for slot in self:
            if slot.start_datetime and slot.end_datetime and slot.start_datetime >= slot.end_datetime:
                raise ValidationError(_("End date must be after start date for shift '%s'.", slot.display_name))

    @api.constrains('employee_id', 'start_datetime', 'end_datetime', 'state', 'active')
    def _check_employee_shift_overlap(self):
        """Prevent overlapping PUBLISHED shifts for the same employee."""
        for slot in self.filtered(lambda s: s.employee_id and s.state == 'published' and s.active):
            # Check for other published shifts for the same employee that overlap
            domain = [
                ('id', '!=', slot.id), ('employee_id', '=', slot.employee_id.id),
                ('state', '=', 'published'), ('active', '=', True),
                ('start_datetime', '<', slot.end_datetime), # Overlap condition
                ('end_datetime', '>', slot.start_datetime),
            ]
            conflicts = self.search(domain, limit=1)
            if conflicts:
                raise ValidationError(_(
                    "Employee '%(emp)s' has a conflicting shift ('%(other_shift)s' from %(start)s to %(end)s) during this period.",
                    emp=slot.employee_id.display_name,
                    other_shift=conflicts.display_name,
                    start=fields.Datetime.context_timestamp(conflicts, conflicts.start_datetime).time(),
                    end=fields.Datetime.context_timestamp(conflicts, conflicts.end_datetime).time()
                ))

    @api.constrains('employee_id', 'start_datetime', 'end_datetime', 'state', 'active')
    def _check_employee_time_off(self):
        """Prevent assigning PUBLISHED shifts during validated time off."""
        for slot in self.filtered(lambda s: s.employee_id and s.state == 'published' and s.active):
            # Odoo's Time Off uses UTC naive dates stored in date_from/date_to
            leaves = self.env['hr.leave'].search([
                ('employee_id', '=', slot.employee_id.id),
                ('state', '=', 'validate'),
                ('date_from', '<', slot.end_datetime), # Time Off starts before shift ends
                ('date_to', '>', slot.start_datetime),   # Time Off ends after shift starts
            ], limit=1)
            if leaves:
                raise ValidationError(_(
                    "Employee '%(emp)s' has validated Time Off ('%(leave)s') that overlaps with this shift.",
                    emp=slot.employee_id.display_name,
                    leave=leaves.holiday_status_id.display_name
                ))

    # --- Actions ---
    def action_publish(self):
        """Publish draft slots and notify employees."""
        if not self: return
        mail_template = self.env.ref('custom_planning.planning_email_template_publish', raise_if_not_found=False)
        slots_to_publish = self.filtered(lambda s: s.state == 'draft')

        # Trigger validation BEFORE writing (more proactive)
        # Note: constraints are checked on write, but explicit call might be desired.
        # slots_to_publish._check_employee_shift_overlap()
        # slots_to_publish._check_employee_time_off()

        slots_to_publish.write({'state': 'published'})

        for slot in slots_to_publish:
             # Try to send email if configured and employee has email/user
            if mail_template and (slot.employee_id.work_email or slot.employee_id.user_id):
                 try:
                    mail_template.send_mail(slot.id, force_send=True, raise_exception=False) # Fail silently on email errors?
                 except Exception as e:
                     _logger.exception("Failed sending planning notification for slot %s. Error: %s", slot.id, e)
            # TODO: Consider creating an activity for the employee's user as a fallback or primary notification

    def action_cancel(self):
        """Cancel published or draft shifts."""
        if not self: return
        # Add any logic needed on cancellation (e.g., cancel activities?)
        self.write({'state': 'cancelled'})

    def action_set_draft(self):
        """Reset cancelled or published shifts back to draft."""
        if not self: return
        self.write({'state': 'draft'})


    # --- Recurrence Actions ---
    def action_generate_recurrence(self):
        """Generates future occurrences based on RRULE for selected template slots."""
        if not self: return
        generated_slots = self.env['planning.slot']

        for template in self:
            if not template.rrule: continue
            if template.recurrence_id:
                raise UserError(_("Cannot generate recurrence from '%s' as it is already an occurrence itself. Use its template '%s'.",
                                  template.display_name, template.recurrence_id.display_name))
            if not template.start_datetime or not template.end_datetime:
                raise UserError(_("Template slot '%s' needs both start and end datetimes defined.", template.display_name))

            # Calculate necessary info from template
            duration = template.end_datetime - template.start_datetime
            start_dt_utc_naive = template.start_datetime

            # Parse RRULE safely
            try:
                rrule_set = rrule.rrulestr(template.rrule, dtstart=start_dt_utc_naive, forceset=True, compatible=True) # compatible might help with edge cases
                until_dt = getattr(rrule_set, '_until', None) # Safer way to get attribute
                if until_dt and until_dt.tzinfo: # Ensure UNTIL is UTC naive
                    until_dt = until_dt.astimezone(pytz.utc).replace(tzinfo=None)
            except Exception as e:
                _logger.exception("Error parsing RRULE '%s' for slot %s", template.rrule, template.id)
                raise UserError(_("Error parsing Recurrence Rule for slot '%s': %s", template.display_name, e))

            # --- Efficiently check existing occurrences for this template ---
            existing_starts = set(self.search_read(
                 [('recurrence_id', '=', template.id)], ['start_datetime']
            ).mapped('start_datetime'))

            max_count = 150 # Safety net
            slots_vals_to_create = []

            # Iterate through calculated occurrences
            occurrence_count = 0
            for occ_start in rrule_set:
                # Skip the very first date if it matches the template start
                if occ_start == start_dt_utc_naive: continue
                # Stop if UNTIL date is reached
                if until_dt and occ_start > until_dt: break
                # Stop if past the template start? Usually only generate future.
                if occ_start < start_dt_utc_naive: continue

                occurrence_count += 1
                if occurrence_count > max_count:
                     _logger.warning("RRULE generation limit (%s) hit for slot %s", max_count, template.id)
                     break

                # Skip if already generated
                if occ_start in existing_starts: continue

                # Prepare values for the new occurrence slot
                occ_end = occ_start + duration
                vals = {
                    'start_datetime': occ_start,
                    'end_datetime': occ_end,
                    'state': 'draft', # Always create as draft
                    'role_id': template.role_id.id, # Keep the role
                    'employee_id': False, # Clear employee by default
                    'notes': template.notes,
                    'company_id': template.company_id.id,
                    'active': True,
                    'rrule': False, # Occurrence does not recur itself
                    'recurrence_id': template.id, # Link back to template
                }
                slots_vals_to_create.append(vals)

            # Create occurrences in batch for performance
            if slots_vals_to_create:
                try:
                    batch_created = self.create(slots_vals_to_create)
                    generated_slots |= batch_created
                    existing_starts.update(s.start_datetime for s in batch_created) # Update for next iteration if multi-template
                except Exception as e:
                    _logger.exception("Batch creation of recurring slots failed for template %s: %s", template.id, e)
                    # Decide how to handle partial failures if needed

        # Provide feedback
        if generated_slots:
            return { # Action to show the new slots
                'name': _('Generated Occurrences'), 'type': 'ir.actions.act_window',
                'res_model': 'planning.slot', 'view_mode': 'gantt,tree,form',
                'domain': [('id', 'in', generated_slots.ids)],
                'target': 'current', # Display in main window
            }
        else: # No NEW slots were generated for any selected template
            return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
                    'title': _("Recurrence Generation"),
                    'message': _("No new future occurrences were generated. They may already exist or the rule has finished."),
                    'type': 'info', 'sticky': False}
                 }


    def action_delete_recurrence(self):
        """Deletes future draft/published occurrences linked to selected templates."""
        if not self: return
        templates = self.filtered(lambda s: s.rrule and not s.recurrence_id)
        if not templates:
            raise UserError(_("Please select template shifts (with a recurrence rule) to delete their future occurrences."))

        now = fields.Datetime.now()
        occurrences_to_delete = self.search([
            ('recurrence_id', 'in', templates.ids),
            ('start_datetime', '>=', now), # Only affect future
            ('state', 'in', ['draft', 'published']), # Don't delete cancelled ones again
        ])

        if not occurrences_to_delete:
            raise UserError(_("No future draft or published occurrences found to delete."))

        count = len(occurrences_to_delete)
        # Confirmation is handled in the view's button definition
        _logger.info("User %s triggering deletion of %s future occurrences for templates: %s", self.env.user.name, count, templates.ids)

        occurrences_to_delete.unlink() # Use unlink for permanent removal

        # Return user feedback
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
                'title': _("Recurrence Deleted"), 'message': _("%s future occurrences deleted successfully.", count),
                'type': 'success', 'sticky': False}
             }

    # --- Utility / Helpers ---
    def _get_employee_tz_object(self):
        """ Returns the employee's timezone object, falling back safely."""
        self.ensure_one()
        employee_tz_str = self.employee_id.tz or self.env.user.tz or self.company_id.resource_calendar_id.tz or 'UTC'
        try:
             return pytz.timezone(employee_tz_str)
        except pytz.UnknownTimeZoneError:
            _logger.warning("Unknown timezone '%s' for employee %s or context. Falling back to UTC.",
                            employee_tz_str, self.employee_id.display_name)
            return pytz.utc