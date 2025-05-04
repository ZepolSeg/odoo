# -*- coding: utf-8 -*-
{
    'name': 'Custom_Planning', # Renamed slightly
    'version': '18.0.1.1.0',
    'category': 'Human Resources/Planning',
    'summary': 'Community Edition employee shift planning with recurrence, conflicts, coverage.',
    'description': """
    Employee shift planning module for Odoo 18 Community, using Calendar View:
    - Roles & Employee assignments
    - Visual Calendar scheduling
    - RRULE recurrence management
    - Conflict detection (Overlaps, Time Off)
    - Min/Max Role Coverage check
    - Statuses (Draft, Published, Cancelled)
    - Week copy utility
    - Live status indicators (basic Attendance/Leave/Conflict check)
    - Email notifications
    - Reporting views (Pivot, Graph, List)
    """,
    'author': 'Your Name / AI Assistant',
    'website': '',
    'depends': [
        'base',
        'hr',
        'hr_holidays', # Time Off module
        # 'web_gantt', # REMOVED - Not in Community
        'calendar',   # Add dependency on calendar for the view type
        'mail',
        'hr_attendance',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/mail_template_data.xml',
        # Wizards
        'wizards/planning_copy_week_views.xml',
        'wizards/planning_check_coverage_views.xml',
        'wizards/planning_quick_create_views.xml', # <-- Définit l'action
        # Views
        'views/planning_role_views.xml',
        'views/planning_slot_views.xml',
        'views/hr_employee_views.xml',
        'views/menus.xml', # <-- Utilise l'action
    ],
    'assets': {
    'web.assets_backend': [
        'custom_planning/static/src/js/planning_list_controller.js',
        # Ajoutez d'autres JS/CSS si nécessaire
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'support': '',
    # Assets remain commented unless custom JS is added later
    }
}