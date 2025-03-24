# filepath: c:\odoo\tutorials\addons_extra\nursery\models\nursery.py
# filepath: c:\odoo\tutorials\addons_extra\nursery\models\nursery.py
from odoo import models, fields

class NurseryPlant(models.Model):
    _name = 'nursery.plant'
    _description = 'Nursery Plant'

    name = fields.Char(string='Plant Name', required=True)
    price = fields.Float(string='Price')

class NurseryCustomer(models.Model):
    _name = 'nursery.customer'
    _description = 'Nursery Customer'

    name = fields.Char(string='Customer Name', required=True)
    email = fields.Char(string='Email', help='To receive the newsletter')