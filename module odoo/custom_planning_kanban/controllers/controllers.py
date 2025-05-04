# -*- coding: utf-8 -*-
# from odoo import http


# class CustomPlanning(http.Controller):
#     @http.route('/custom_planning/custom_planning', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/custom_planning/custom_planning/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('custom_planning.listing', {
#             'root': '/custom_planning/custom_planning',
#             'objects': http.request.env['custom_planning.custom_planning'].search([]),
#         })

#     @http.route('/custom_planning/custom_planning/objects/<model("custom_planning.custom_planning"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('custom_planning.object', {
#             'object': obj
#         })

