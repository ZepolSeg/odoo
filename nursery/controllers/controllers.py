# -*- coding: utf-8 -*-
# from odoo import http


# class Nursery(http.Controller):
#     @http.route('/nursery/nursery', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/nursery/nursery/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('nursery.listing', {
#             'root': '/nursery/nursery',
#             'objects': http.request.env['nursery.nursery'].search([]),
#         })

#     @http.route('/nursery/nursery/objects/<model("nursery.nursery"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('nursery.object', {
#             'object': obj
#         })

