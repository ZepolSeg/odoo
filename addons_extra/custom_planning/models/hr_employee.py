# -*- coding: utf-8 -*-
from odoo import models, fields

class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    planning_role_ids = fields.Many2many(
        comodel_name='planning.role',
        relation='planning_employee_role_rel',
        column1='employee_id',
        column2='role_id',
        string='Planning Roles',
        help="Roles this employee can be assigned to in planning shifts."
    )

    # The 'tz' (timezone) field is inherited from resource.mixin, linked typically
    # through resource.resource -> hr.employee. It should be available by default.
    # Example: Access via self.employee_id.tz