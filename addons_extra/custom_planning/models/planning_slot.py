# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from dateutil.relativedelta import relativedelta
from dateutil import rrule
from dateutil.parser import parse
import pytz
from datetime import datetime, time, timedelta
import logging

_logger = logging.getLogger(__name__)

class PlanningSlot(models.Model):
    _name = 'planning.slot'
    _description = 'Planning Shift / Slot'
    _order = 'start_datetime, id' # Added id for consistent ordering
    _inherit = ['mail.thread', 'mail.activity.mixin']

    # --- Core Fields ---
    name = fields.Char("Description", compute='_compute_display_name', store=True, readonly=False)
    active = fields.Boolean(default=True, tracking=True, index=True,
                            help="If the active field is set to False, it will allow you to hide the planning slot without removing it.")
    employee_id = fields.Many2one(
        'hr.employee', string="Employee", tracking=True, copy=False, index=True
    )
    role_id = fields.Many2one(
        'planning.role', string="Required Role", tracking=True, index=True
    )
    start_datetime = fields.Datetime("Start DateTime", required=True, index=True, tracking=True)
    end_datetime = fields.Datetime("End DateTime", required=True, index=True, tracking=True)
    duration = fields.Float("Duration (Hours)", compute='_compute_duration', store=True)
    # Alloc % is useful in Gantt if employees can have multiple overlapping slots
    # allocation_percentage = fields.Float("Allocation (%)", default=100.0, tracking=True)
    color = fields.Integer("Color Index", related='role_id.color', readonly=True, store=False) # Display only
    notes = fields.Text("Notes")
    company_id = fields.Many2one('res.company', string='Company', required=True, default=lambda self: self.env.company)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('cancelled', 'Cancelled'),
        ], string='Status', default='draft', required=True, copy=False, tracking=True, index=True)

    # --- Recurrence Fields ---
    rrule = fields.Char('Recurrence Rule (RRULE)', help="Define recurrence using iCalendar RRULE format. Leave empty for non-recurring slots.")
    recurrence_id = fields.Many2one('planning.slot', string="Recurrence Template", index=True, ondelete='cascade', readonly=True, copy=False) # Cascade delete occurrences if template deleted? Or set null? Cascade is simpler for now.
    # If managing single occurrence modifications:
    # recurrence_original_start = fields.Datetime("Original Start (for exceptions)", readonly=True, copy=False)
    # is_recurrence_exception = fields.Boolean("Is Recurrence Exception", default=False, copy=False)

    # --- Computed Fields for Live Status ---
    # Note: Making these compute non-stored. For performance, consider making them stored + computed by cron.
    attendance_state = fields.Selection([
            ('present', 'Present'),
            ('absent', 'Absent'),
            ('late', 'Late'),
            ('early_out','Early Out'),
            ('leave', 'On Leave'),
            ('scheduled', 'Scheduled'), # Future or unconfirmed state
            ('off', 'Off / Cancelled'),
            ('conflicting','Conflicting Shift')
        ], string="Live Status", compute='_compute_live_status', store=False, search='_search_attendance_state')

    has_conflict = fields.Boolean(compute='_compute_live_status', store=False) # Helper for UI logic

    # --- Compute Methods ---
    @api.depends('start_datetime', 'end_datetime')
    def _compute_duration(self):
        for slot in self:
            if slot.start_datetime and slot.end_datetime:
                delta = slot.end_datetime - slot.start_datetime
                slot.duration = delta.total_seconds() / 3600.0
            else:
                slot.duration = 0.0

        # Dépendances restent les mêmes
    @api.depends('employee_id.name', 'role_id.name', 'start_datetime')
    def _compute_display_name(self):
        for slot in self:
            name_parts = []
            # Sécurités pour les NewId et accès aux noms
            current_role = slot.role_id #.exists() # exists() peut être utile mais testons sans d'abord
            current_employee = slot.employee_id #.exists()

            if current_role and current_role.name:
                name_parts.append(current_role.name)
            if current_employee and current_employee.name:
                name_parts.append(current_employee.name)

            if not name_parts and slot.start_datetime:
                try:
                    user_tz = slot.employee_id.tz or self.env.user.tz or 'UTC'
                    dt_to_format = slot.start_datetime
                    localized_dt = fields.Datetime.context_timestamp(slot.with_context(tz=user_tz), dt_to_format)
                    name_parts.append(localized_dt.strftime('%H:%M'))
                except Exception as e:
                    _logger.debug("Could not format time for display name: %s", e)
                    pass # Continue sans l'heure si formatage échoue

            # Fallback final
            if not name_parts:
                name_parts.append(_("Slot"))

            # ---> CORRECTION ICI <---
            # 1. Créer la variable computed_name
            computed_name = " - ".join(name_parts)
            # 2. Assigner à slot.name
            slot.name = computed_name
            # 3. Assigner à slot.display_name
            slot.display_name = computed_name
    @api.depends('employee_id', 'start_datetime', 'end_datetime', 'state', 'active')
    def _compute_live_status(self):
        """
        Calculates the live status: checks leaves, conflicts, and attendances.
        This is computationally intensive and not optimized for very large datasets without `store=True` and cron.
        """
        # Optimization idea: Handle slots without employee / date / active quickly
        inactive_or_unassigned = self.filtered(lambda s: not s.active or s.state == 'cancelled' or not s.employee_id or not s.start_datetime or not s.end_datetime)
        inactive_or_unassigned.attendance_state = 'off'
        inactive_or_unassigned.has_conflict = False

        slots_to_process = self - inactive_or_unassigned
        if not slots_to_process:
            return

        now = fields.Datetime.now() # UTC Now
        employee_ids = slots_to_process.mapped('employee_id.id')
        min_start = min(slots_to_process.mapped('start_datetime')) - timedelta(days=1) # Wider range for safety
        max_end = max(slots_to_process.mapped('end_datetime')) + timedelta(days=1)

        leaves_data = self._get_employee_data('hr.leave', employee_ids, min_start, max_end, [
            ('state', '=', 'validate'),
            ('date_from', '<', max_end),
            ('date_to', '>', min_start),
        ])

        conflicts_data = self._get_employee_data('planning.slot', employee_ids, min_start, max_end, [
            ('state', '=', 'published'),
            ('active', '=', True),
            ('start_datetime', '<', max_end),
            ('end_datetime', '>', min_start),
        ])

        # Attendance data is tricky. Getting the *last* attendance per employee is most common.
        attendances = self.env['hr.attendance'].search([
            ('employee_id', 'in', employee_ids),
            # Minimal filtering here; need latest check-in/out info
        ], order='check_in desc')
        last_attendance_map = {emp_id: None for emp_id in employee_ids}
        for att in attendances:
             if last_attendance_map[att.employee_id.id] is None:
                 last_attendance_map[att.employee_id.id] = att

        for slot in slots_to_process:
            start_utc = slot.start_datetime
            end_utc = slot.end_datetime
            emp_id = slot.employee_id.id
            state = 'scheduled'
            has_conflict_flag = False

            # 1. Check Leaves (Validated)
            is_on_leave = any(
                leave['date_from'] < end_utc and leave['date_to'] > start_utc
                for leave in leaves_data.get(emp_id, [])
            )
            if is_on_leave:
                slot.attendance_state = 'leave'
                slot.has_conflict = False
                continue

            # 2. Check Conflicts (Other published, active slots)
            if slot.state == 'published': # Only published slots can truly conflict
                 is_conflicting = any(
                     conflict['id'] != slot.id and # Don't conflict with self
                     conflict['start_datetime'] < end_utc and conflict['end_datetime'] > start_utc
                     for conflict in conflicts_data.get(emp_id, [])
                 )
                 if is_conflicting:
                     has_conflict_flag = True
                     # We record the conflict but continue to check attendance status
                     state = 'conflicting'

            slot.has_conflict = has_conflict_flag

             # 3. Check Attendance (Based on last record) - Simplified Logic
            last_att = last_attendance_map.get(emp_id)
            att_state = 'scheduled' # Default if no relevant attendance
            if end_utc < now: att_state = 'absent' # If past and no relevant attendance

            if last_att:
                 check_in = last_att.check_in
                 check_out = last_att.check_out

                 # Is attendance currently active?
                 is_att_active = not check_out

                 # Does the last attendance overlap with the slot?
                 att_overlaps = check_in < end_utc and (not check_out or check_out > start_utc)

                 if att_overlaps:
                     if is_att_active: # Currently checked in
                         if check_in > start_utc: att_state = 'late'
                         else: att_state = 'present'
                     else: # Checked out during or after the slot
                         if check_out < end_utc: att_state = 'early_out'
                         elif check_in > start_utc: att_state = 'late' # Late start, finished on time/late
                         else: att_state = 'present' # Attended the full duration (or more) covered by this record
                 else:
                      # Attendance record doesn't overlap slot.
                      if start_utc < now: # Slot has started or passed
                         att_state = 'absent' # No relevant attendance found

                 # Refinement needed here for better accuracy with multiple attendances in a day.


            # Final state: 'conflicting' has precedence visually if set
            slot.attendance_state = state if state == 'conflicting' else att_state


    def _get_employee_data(self, model_name, employee_ids, date_from, date_to, domain):
        """ Helper to fetch date-ranged data grouped by employee ID. """
        data = self.env[model_name].search_read(
            domain + [('employee_id', 'in', employee_ids)],
            ['id', 'employee_id', 'date_from', 'date_to', 'start_datetime', 'end_datetime'], # Include all potential date fields
            order='employee_id'
        )
        grouped_data = defaultdict(list)
        for item in data:
            # Normalize date fields if model has different names
            item_start = item.get('start_datetime') or item.get('date_from')
            item_end = item.get('end_datetime') or item.get('date_to')
            if not item_start or not item_end: continue # Skip if dates missing

            item['start_datetime'] = item_start # Normalize
            item['end_datetime'] = item_end   # Normalize

            grouped_data[item['employee_id'][0]].append(item)
        return grouped_data

    # Search function for attendance_state (Example - VERY Basic)
    # Proper search requires complex joins/subqueries and is better done via SQL Views or ORM override
    def _search_attendance_state(self, operator, value):
        # This is a placeholder - searching on a non-stored computed field like this
        # is inefficient and often inaccurate. Returning a broad domain.
        _logger.warning("Searching on non-stored field 'attendance_state' is inefficient and may be inaccurate.")
        if operator == '=' and value == 'leave':
             # Find employees currently on leave and return their slots
            # This is complex to do accurately without knowing the exact time range of the search
            return [('id', 'in', [])] # TODO: Implement real search if needed
        # Fallback to searching all slots (likely requires further filtering)
        return [('id', '!=', 0)]


    # --- Constraints ---
    @api.constrains('start_datetime', 'end_datetime')
    def _check_dates(self):
        for slot in self:
            if slot.start_datetime and slot.end_datetime and slot.start_datetime >= slot.end_datetime:
                raise ValidationError(_("Shift '%s': End date must be strictly after start date.", slot.display_name))

    @api.constrains('employee_id', 'start_datetime', 'end_datetime', 'state', 'active')
    def _check_employee_conflicts(self):
        """ Checks for overlapping shifts for the same employee (only compares published+active) """
        for slot in self.filtered(lambda s: s.employee_id and s.state == 'published' and s.active):
            domain = [
                ('id', '!=', slot.id),
                ('employee_id', '=', slot.employee_id.id),
                ('state', '=', 'published'),
                ('active', '=', True),
                ('start_datetime', '<', slot.end_datetime), # Overlap logic
                ('end_datetime', '>', slot.start_datetime),
            ]
            conflicting_slots = self.search(domain, limit=1)
            if conflicting_slots:
                raise ValidationError(_(
                    "Employee '%(employee)s' has a conflicting published shift (%(conflict_name)s from %(start)s to %(end)s) during the period of '%(slot_name)s'.",
                    employee=slot.employee_id.name,
                    conflict_name=conflicting_slots.display_name,
                    start=fields.Datetime.context_timestamp(conflicting_slots, conflicting_slots.start_datetime).strftime('%H:%M'),
                    end=fields.Datetime.context_timestamp(conflicting_slots, conflicting_slots.end_datetime).strftime('%H:%M'),
                    slot_name=slot.display_name
                ))

    @api.constrains('employee_id', 'start_datetime', 'end_datetime', 'state', 'active')
    def _check_employee_leave(self):
        """ Checks if the employee has validated leave during the shift (published+active only) """
        for slot in self.filtered(lambda s: s.employee_id and s.state == 'published' and s.active and s.start_datetime and s.end_datetime):
            start_utc = slot.start_datetime
            end_utc = slot.end_datetime
            # hr.leave uses UTC naive date_from/date_to
            domain = [
                ('employee_id', '=', slot.employee_id.id),
                ('state', '=', 'validate'),
                ('date_from', '<', end_utc), # Leave starts before shift ends
                ('date_to', '>', start_utc),   # Leave ends after shift starts
            ]
            conflicting_leaves = self.env['hr.leave'].search(domain, limit=1)
            if conflicting_leaves:
                raise ValidationError(_(
                    "Employee '%(employee)s' is on validated leave ('%(leave_type)s') overlapping with the shift '%(slot_name)s'.",
                    employee=slot.employee_id.name,
                    leave_type=conflicting_leaves.holiday_status_id.name,
                    slot_name=slot.display_name
                ))

    # --- Actions ---
    def action_publish(self):
        mail_template = self.env.ref('custom_planning.planning_email_template_publish', raise_if_not_found=False)
        published_slots = self.filtered(lambda s: s.state == 'draft')
        if not published_slots: return True

        # Optional: Trigger constraint checks *before* writing state?
        # try:
        #    published_slots.check_constraints() # Check explicitly
        # except (ValidationError, UserError) as e:
        #     raise UserError(_("Cannot publish. Validation Error: %s") % e.args[0])

        published_slots.write({'state': 'published'})

        # Send emails / notifications
        for slot in published_slots.filtered(lambda s: s.employee_id.user_id or s.employee_id.work_email):
            if mail_template:
                 try:
                     mail_template.send_mail(slot.id, force_send=True, raise_exception=True) # raise_exception helps debug template/smtp issues
                 except Exception as e:
                     _logger.error("Failed to send planning notification email for slot %s (employee %s): %s", slot.id, slot.employee_id.name, e)
            # Fallback/alternative: create activity for user
            # elif slot.employee_id.user_id:
            #     slot.activity_schedule(...)


    def action_cancel(self):
        # Check if already cancelled?
        if all(slot.state == 'cancelled' for slot in self): return True
        # Cancel associated activities?
        # ...
        self.write({'state': 'cancelled'})

    def action_set_draft(self):
         self.write({'state': 'draft'})


    # --- Recurrence Methods ---
    def action_generate_recurrence(self):
        """ Generates recurring slots based on RRULE for the selected templates """
        new_slots_map = defaultdict(lambda: self.env['planning.slot']) # Map template_id -> new_slots
        templates_processed = self.env['planning.slot']

        for template in self:
            if not template.rrule: continue
            if not template.start_datetime or not template.end_datetime:
                 raise UserError(_("Template slot '%s' lacks start/end time.", template.display_name))
            if template.recurrence_id:
                 raise UserError(_("Slot '%s' is already an occurrence. Generate from the template: %s", template.display_name, template.recurrence_id.display_name))

            templates_processed |= template
            duration = template.end_datetime - template.start_datetime
            start_dt_utc_naive = template.start_datetime

            try:
                rrule_options = rrule.rrulestr(template.rrule, dtstart=start_dt_utc_naive, forceset=True)
                until_dt = rrule_options._until
                if until_dt and until_dt.tzinfo: # Convert until date to UTC naive if needed
                    until_dt = until_dt.astimezone(pytz.utc).replace(tzinfo=None)
            except Exception as e:
                raise UserError(_("Error parsing RRULE for slot '%s': %s", template.display_name, e))

            count = 0
            max_count = 150 # Safety limit increased slightly
            existing_occurrences = self.search_read(
                [('recurrence_id', '=', template.id)], ['start_datetime']
                )
            existing_starts = {o['start_datetime'] for o in existing_occurrences}

            for occurrence_start in rrule_options:
                if occurrence_start == start_dt_utc_naive: continue # Skip the template date itself
                if until_dt and occurrence_start > until_dt: break
                if occurrence_start < start_dt_utc_naive: continue # Skip past events relative to template

                count += 1
                if count > max_count:
                    _logger.warning("RRULE limit (%s) reached for slot %s", max_count, template.id)
                    break

                if occurrence_start in existing_starts:
                     continue # Already exists

                occurrence_end = occurrence_start + duration

                vals = template.copy_data({
                    'start_datetime': occurrence_start,
                    'end_datetime': occurrence_end,
                    'state': 'draft',
                    'employee_id': False, # Do not copy employee by default
                    'role_id': template.role_id.id, # Keep the role
                    'rrule': False,
                    'recurrence_id': template.id,
                    'active': True,
                     'notes': template.notes, # Copy notes? Maybe optional.
                    'company_id': template.company_id.id,
                })[0]
                vals.pop('message_follower_ids', None) # Don't copy followers

                try:
                    # Use low level create for potentially better performance if creating many
                    new_slot = self.create(vals)
                    new_slots_map[template.id] |= new_slot
                except ValidationError as ve:
                    _logger.warning("Validation Error creating occurrence for template %s at %s: %s", template.id, occurrence_start, ve)
                except Exception as ex:
                     _logger.error("Unexpected Error creating occurrence for template %s at %s: %s", template.id, occurrence_start, ex)

        # Show generated slots
        all_new_slots = self.env['planning.slot'].concat(*new_slots_map.values())
        if all_new_slots:
             return {
                 'name': _('Generated Recurring Slots'),
                 'type': 'ir.actions.act_window',
                 'res_model': 'planning.slot',
                 'view_mode': 'gantt,tree,form',
                 'domain': [('id', 'in', all_new_slots.ids)],
                  # Focus view on the period of the generated slots if possible
                  # 'context': {'default_date_start': ..., 'default_date_end': ...}
             }
        elif templates_processed:
            # Let user know if template was processed but no *new* slots created
            return {
                 'type': 'ir.actions.client',
                 'tag': 'display_notification',
                 'params': {
                     'title': _("Recurrence Generation"),
                     'message': _("No new recurring slots generated for the selected template(s). They might already exist or the RRULE finished."),
                     'sticky': False,
                     'type': 'info',
                     }
                 }


    def action_delete_recurrence(self):
        """ Deletes FUTURE draft/published occurrences linked to the selected templates. """
        templates = self.filtered(lambda s: s.rrule and not s.recurrence_id)
        if not templates:
            raise UserError(_("Select template slots (with RRULE, not occurrences) to delete their future recurrences."))

        occurrences_to_delete = self.env['planning.slot']
        now = fields.Datetime.now()

        for template in templates:
             domain = [
                 ('recurrence_id', '=', template.id),
                 ('start_datetime', '>=', now), # Only future relative to now
                 ('state', 'in', ['draft','published']) # Only delete draft/published
             ]
             occurrences_to_delete |= self.search(domain)

        if not occurrences_to_delete:
             raise UserError(_("No future draft or published occurrences found to delete for the selected template(s)."))

        # Confirmation is handled by the button `confirm="..."` in the view
        _logger.info("User %s deleting %s future occurrences for planning templates %s", self.env.user.name, len(occurrences_to_delete), templates.ids)
        # Unlink is irreversible. Consider archiving or cancelling instead?
        occurrences_to_delete.unlink()

        # Optionnel: Notifier ? Ou retourner une notification client.
        return {
             'type': 'ir.actions.client',
             'tag': 'display_notification',
             'params': {
                 'title': _("Recurrence Deletion"),
                 'message': _("%s future occurrences deleted.", len(occurrences_to_delete)),
                 'sticky': False,
                 'type': 'success',
             }
        }

    # --- Utility / Helpers ---
    def _get_employee_tz(self):
        self.ensure_one()
        return pytz.timezone(self.employee_id.tz or self.env.user.tz or self.company_id.resource_calendar_id.tz or 'UTC')

    # --- ORM Overrides (Optional - e.g., prevent editing published/cancelled) ---
    # def write(self, vals):
    #    if 'state' not in vals and any(s.state in ('published', 'cancelled') for s in self) and not self.env.context.get('bypass_planning_state_check'):
    #        editable_fields = ['notes', 'active'] # Fields allowed to change when published/cancelled
    #        if any(field not in editable_fields for field in vals.keys()):
    #            raise UserError(_("Cannot modify published or cancelled shifts directly. Set to Draft first to change core details."))
    #    return super().write(vals)