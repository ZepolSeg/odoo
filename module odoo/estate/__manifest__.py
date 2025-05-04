{
    'name': 'Estate',
    'version': '1.0',
    'category': 'Real Estate',
    'summary': 'Real Estate Management Module',
    'description': """
        Module for managing real estate properties.
    """,
    'author': 'Your Name',
    'website': 'https://yourwebsite.com',
    'license': 'LGPL-3',
    'depends': ['base'],
    'data': [
        'security/ir.model.access.csv',
        'views/estate_property_views.xml',
    ],
    'installable': True,
    'application': True,  # Cette ligne rend le module visible dans les Apps
    'auto_install': False,
}
