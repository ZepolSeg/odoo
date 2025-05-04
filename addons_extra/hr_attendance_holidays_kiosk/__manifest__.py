# -*- coding: utf-8 -*-
{
    'name': "hr_attendance_holidays_kiosk",
    'summary': """Allows employees to request time off directly from the Attendance Kiosk.""",
    'description': """
        Adds a button to the HR Attendance Kiosk screen allowing employees
        to select themselves and then request a time off (leave/absence)
        instead of checking in/out.
    """,
    'author': "Your Name / Company",
    'website': "your_website.com",
    'category': 'Human Resources/Attendances',
    'version': '18.0.1.1.0', # Adaptez à votre version d'Odoo
    'depends': [
        'hr_attendance',
        'hr_holidays', # Dépendance essentielle !
    ],
    'data': [
        'views/hr_attendance_kiosk_templates.xml',
    ],
    'assets': {
        'web.assets_backend': [
        #    'hr_attendance_holidays_kiosk/static/src/scss/kiosk_mode_holidays.scss', # Optionnel
            'hr_attendance_holidays_kiosk/static/src/js/kiosk_mode_holidays.js',
            'hr_attendance_holidays_kiosk/static/src/xml/kiosk_mode_holidays.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False, # Peut être mis à True si vous voulez qu'il s'installe dès que hr_attendance et hr_holidays sont là
    'license': 'LGPL-3', # Ou votre licence préférée
}