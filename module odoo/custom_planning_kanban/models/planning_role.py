# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class PlanningRole(models.Model):
    _name = 'planning.role'
    _description = 'Planning Role'
    _order = 'sequence, name'

    name = fields.Char("Role Name", required=True, translate=True)
    sequence = fields.Integer('Sequence', default=10)
    active = fields.Boolean(default=True, help="Set active to false to hide this role without removing it.")
    color = fields.Integer("Color Index", default=0, help="Color used for Gantt and Calendar views.")
    employee_ids = fields.Many2many(
        comodel_name='hr.employee', # Use comodel_name in Odoo 14+
        relation='planning_employee_role_rel', # Explicit relation table name
        column1='role_id',
        column2='employee_id',
        string='Employees with this Role',
        help="Employees qualified or usually assigned to this role."
    )

    # Coverage Requirements
    min_required_daily = fields.Integer(
        string="Min Required per Day", default=0,
        help="Minimum number of unique employees needed for this role on any given day (checks published shifts). Set 0 to disable."
    )
    max_allowed_daily = fields.Integer(
        string="Max Allowed per Day", default=0,
        help="Maximum number of unique employees allowed for this role on any given day (checks published shifts). Set 0 to disable."
    )

    @api.constrains('min_required_daily', 'max_allowed_daily')
    def _check_min_max_values(self):
        """Validate min/max coverage values."""
        for record in self:
            if record.min_required_daily < 0 or record.max_allowed_daily < 0:
                raise ValidationError(_("Coverage limits cannot be negative for role '%s'.", record.name))
            if record.max_allowed_daily > 0 and record.min_required_daily > record.max_allowed_daily:
                raise ValidationError(_("Max Allowed (%s) cannot be less than Min Required (%s) for role '%s'.",
                                        record.max_allowed_daily, record.min_required_daily, record.name))