# controllers/main.py
# -*- coding: utf-8 -*-
import logging
from odoo import http
from odoo.http import request
from odoo.exceptions import UserError, AccessError
from odoo.tools.translate import _
import pytz # Import pour la gestion des fuseaux horaires

_logger = logging.getLogger(__name__)

class HrHolidaysKioskController(http.Controller):

    def _get_employee_tz_info(self, employee_id):
        """ Helper to get employee's timezone """
        employee = request.env['hr.employee'].browse(employee_id).sudo() # Use sudo carefully
        tz = employee.tz or employee.resource_calendar_id.tz or request.env.user.tz or 'UTC'
        return {'tz': tz}

    def _convert_to_utc(self, dt_str, tz_name):
        """ Convert a naive datetime string from a given timezone to UTC """
        if not dt_str:
            return None
        try:
            local_tz = pytz.timezone(tz_name)
            naive_dt = http.datetime.datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
            local_dt = local_tz.localize(naive_dt, is_dst=None)
            utc_dt = local_dt.astimezone(pytz.utc)
            return utc_dt.strftime('%Y-%m-%d %H:%M:%S')
        except Exception as e:
            _logger.error(f"Error converting datetime {dt_str} from tz {tz_name} to UTC: {e}")
            # Fallback or raise error? Fallback to naive string for now.
            return dt_str


    @http.route('/hr_holidays/kiosk/request_time_off', type='json', auth='user', methods=['POST'])
    def kiosk_request_time_off(self, employee_id, leave_type_id, date_from, date_to, name=None):
        """
            Endpoint called by the Kiosk JS to create a leave request.
            date_from and date_to are expected as strings like 'YYYY-MM-DD HH:MM:SS'
            Potentially naive datetime strings from JS based on browser/kiosk local time.
        """
        _logger.info(f"Received kiosk time off request for employee {employee_id}, type {leave_type_id}, from {date_from} to {date_to}")

        try:
            # Vérification de base des permissions (l'utilisateur connecté peut-il faire ça ?)
            # Idéalement, la logique de sécurité devrait être plus fine.
            # Est-ce que l'utilisateur loggué dans le kiosque a le droit de créer un congé pour cet employé ?
            # Pour l'instant, on se fie à `auth='user'` et on essaie la création.
            # Le modèle hr.leave a ses propres contrôles d'accès.

            # Important: Gestion des fuseaux horaires
            # Le JS envoie probablement des dates/heures locales au navigateur/kiosque.
            # Odoo stocke en UTC. Il faut convertir.
            employee_tz_info = self._get_employee_tz_info(employee_id)
            tz_name = employee_tz_info['tz']

            utc_date_from = self._convert_to_utc(date_from, tz_name)
            utc_date_to = self._convert_to_utc(date_to, tz_name)

            if not utc_date_from or not utc_date_to:
                 raise UserError(_("Format de date invalide reçu."))

            # Utiliser sudo() est souvent nécessaire car l'utilisateur 'public' ou l'utilisateur du kiosque
            # n'a peut-être pas les droits directs sur l'employé ou hr.leave.
            # C'est un point de sécurité à considérer attentivement.
            # Une meilleure approche pourrait être de faire l'action en tant qu'employé lui-même s'il a un user lié,
            # ou via un utilisateur RH spécifique. Sudo() est le plus simple mais large.
            Employee = request.env['hr.employee'].sudo().browse(employee_id)
            if not Employee.exists():
                return {'success': False, 'error': _("Employé non trouvé.")}

            # Préparer les valeurs pour la création
            vals = {
                'employee_id': employee_id,
                'holiday_status_id': leave_type_id,
                'request_date_from': utc_date_from,
                'request_date_to': utc_date_to,
                'name': name or '',
                # 'state': 'confirm', # Mettre directement à confirmer ? Ou laisser la valeur par défaut?
                                    # Laisser par défaut est souvent mieux pour déclencher les automatisations/workflows.
                # Si vous voulez le faire au nom de l'employé s'il a un user :
                # 'user_id': Employee.user_id.id if Employee.user_id else request.env.user.id,
            }

            # Créer la demande de congé
            # On utilise sudo() pour passer outre les access rules potentielles de l'utilisateur courant,
            # mais les contraintes du modèle (ex: chevauchement) s'appliqueront toujours.
            leave = request.env['hr.leave'].sudo().create(vals)

            # Logique optionnelle : tenter de confirmer ou valider automatiquement ?
            # Cela dépend de la politique de l'entreprise et de la configuration du type de congé.
            # Exemple : Si c'est un type 'Maladie' qui doit être auto-approuvé:
            # leave_type = request.env['hr.leave.type'].sudo().browse(leave_type_id)
            # if leave_type.validation_type == 'no_validation': # ou un flag custom 'auto_approve_from_kiosk'
            #    try:
            #        leave.sudo().action_approve()
            #         if leave.validation_type == 'both': # S'il y a double validation
            #              leave.sudo().action_validate()
            #    except Exception as e:
            #        _logger.warning(f"Could not auto-approve leave {leave.id}: {e}")

            _logger.info(f"Leave request {leave.id} created for employee {employee_id}")
            return {'success': True, 'leave_id': leave.id}

        except AccessError as e:
             _logger.error(f"Access Denied during kiosk leave request: {e}")
             return {'success': False, 'error': _("Accès refusé.")}
        except UserError as e: # Erreurs fonctionnelles (ex: chevauchement, allocation)
             _logger.warning(f"UserError during kiosk leave request: {e}")
             return {'success': False, 'error': str(e)}
        except Exception as e:
            _logger.exception("Error during kiosk leave request creation:")
            # Ne pas retourner de détails techniques au client
            return {'success': False, 'error': _("Une erreur interne est survenue lors de la création de la demande.")}