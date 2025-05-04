# -*- coding: utf-8 -*-
{
    'name': 'Custom_Planning',
    'version': '18.0.1.1.0', # Version for Odoo 18
    'category': 'Human Resources/Planning',
    'summary': 'Advanced employee shift planning: recurrence, conflicts, coverage, live status.',
    'description': """
    Employee shift planning module for Odoo 18 Community, including:
    - Roles & Employee assignments
    - Visual Gantt scheduling with Drag & Drop
    - RRULE recurrence management
    - Conflict detection (Overlaps, Time Off)
    - Min/Max Role Coverage check
    - Statuses (Draft, Published, Cancelled)
    - Week copy utility
    - Live status indicators (basic Attendance/Leave/Conflict check)
    - Email notifications
    - Reporting views
    """,
    'author': 'Your Name / AI Assistant',
    'website': '', # Add your website here
    'depends': [
        'base',
        'hr',         # hr.employee
        'hr_holidays',# hr.leave (Time Off)
        'web_gantt',  # Gantt view
        'mail',       # Chatter, Mail templates
        'hr_attendance', # Needed for _compute_live_status - make dependency explicit
    ],
    'data': [
        # Security
        'security/ir.model.access.csv',

        # Data
        'data/mail_template_data.xml',

        # Wizards
        'wizards/planning_copy_week_views.xml',
        'wizards/planning_check_coverage_views.xml',

        # Views
        'views/planning_role_views.xml',
        'views/planning_slot_views.xml',
        'views/hr_employee_views.xml',
        'views/menus.xml',

    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'support': '', # Add contact email
    # 'assets': { # Uncomment and add paths if JS/CSS customization is done later
    #     'web.assets_backend': [
    #         'custom_planning/static/src/...',
    #     ],
    # }
}