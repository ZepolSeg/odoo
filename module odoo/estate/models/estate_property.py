#-*- coding: utf-8 -*-
#Part of Odoo. See LICENSE file for full copyright and licensing details.
from odoo import models, fields

class EstateProperty(models.Model):
    _name = 'estate.property'
    _description = 'Estate Property'

    name = fields.Char(string='Name', required=True)
    description = fields.Text(string='Description')
    postcode = fields.Char(string='Postcode')
    date_availability = fields.Date(string='Date Availability')
    expected_price = fields.Float(string='Expected Price', required=True)
    selling_price = fields.Float(string='Selling Price')
    bedrooms = fields.Integer(string='Bedrooms')
    living_area = fields.Integer(string='Living Area (sqm)')
    facades = fields.Integer(string='Facades')
    garage = fields.Boolean(string='Garage')
    garden = fields.Boolean(string='Garden')
    garden_area = fields.Integer(string='Garden Area (sqm)')
    garden_orientation = fields.Selection(
        [('north', 'North'), 
         ('south', 'South'), 
         ('east', 'East'), 
         ('west', 'West')],
        string='Garden Orientation'
    )
    create_uid = fields.Many2one('res.users', string='Created by', readonly=True)
    create_date = fields.Datetime(string='Created on', readonly=True)
    write_uid = fields.Many2one('res.users', string='Modified by', readonly=True)
    write_date = fields.Datetime(string='Modified on', readonly=True)
    