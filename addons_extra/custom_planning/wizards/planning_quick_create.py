# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import timedelta
import logging

_logger = logging.getLogger(__name__)

class PlanningQuickCreateWizard(models.TransientModel):
    _name = 'planning.quick.create.wizard'
    _description = 'Planning: Quick Create Slot Wizard'

    employee_id = fields.Many2one(
        'hr.employee', string="Employee", required=True,
        help="Select the employee to assign the shift(s) to."
    )
    # Note: Filtrage dynamique du rôle basé sur l'employé dans la vue XML
    role_id = fields.Many2one(
        'planning.role', string="Role", required=True,
        help="Select the role for the shift(s)."
    )
    start_datetime = fields.Datetime("Start DateTime", required=True)
    end_datetime = fields.Datetime("End DateTime", required=True)

    # Options de répétition simples
    repeat_type = fields.Selection([
        ('none', 'Do not repeat'),
        ('n_weeks', 'Repeat Weekly for N Weeks'),
        # Ajouter d'autres options plus tard si besoin ('daily', 'n_days', etc.)
        ], string="Repeat", default='none', required=True)

    repeat_count = fields.Integer(
        string="Number of Additional Weeks", default=1,
        help="How many *additional* weeks should this shift be repeated (e.g., 1 means the shift occurs this week and the next week)."
    )
    # repeat_interval = fields.Integer(string="Repeat Every", default=1) # Pour "toutes les X semaines"

    # Contraintes
    @api.constrains('start_datetime', 'end_datetime')
    def _check_dates(self):
        for wizard in self:
            if wizard.start_datetime and wizard.end_datetime and wizard.start_datetime >= wizard.end_datetime:
                raise ValidationError(_("End date must be strictly after start date."))

    @api.constrains('repeat_type', 'repeat_count')
    def _check_repeat_count(self):
        for wizard in self:
            if wizard.repeat_type == 'n_weeks' and wizard.repeat_count < 1:
                raise ValidationError(_("Number of additional weeks must be at least 1 when repeating weekly."))

    # Action principale
    def action_create_slots(self):
        self.ensure_one()
        created_slots = self.env['planning.slot']
        slot_vals_list = []

        # --- Préparer les données du premier créneau ---
        first_slot_vals = {
            'employee_id': self.employee_id.id,
            'role_id': self.role_id.id,
            'start_datetime': self.start_datetime,
            'end_datetime': self.end_datetime,
            'company_id': self.employee_id.company_id.id or self.env.company.id,
            'state': 'draft', # Toujours créer en brouillon via le wizard rapide
            'active': True,
        }
        slot_vals_list.append(first_slot_vals)

        # --- Préparer les répétitions (si demandées) ---
        if self.repeat_type == 'n_weeks':
            current_start = self.start_datetime
            current_end = self.end_datetime
            for i in range(self.repeat_count):
                # Calculer les dates de la semaine suivante
                # Utilise timedelta, attention aux DST si non géré via UTC
                current_start += timedelta(weeks=1)
                current_end += timedelta(weeks=1)

                repeat_slot_vals = first_slot_vals.copy()
                repeat_slot_vals.update({
                    'start_datetime': current_start,
                    'end_datetime': current_end,
                })
                slot_vals_list.append(repeat_slot_vals)

        # --- Créer tous les créneaux en batch ---
        if slot_vals_list:
            try:
                # TODO: Ajouter une vérification optionnelle de conflit/congé ici avant create?
                # Pour un wizard "rapide", on peut choisir de sauter cette étape
                # ou d'ajouter un flag "Ignorer conflits".
                created_slots = self.env['planning.slot'].create(slot_vals_list)
                _logger.info(f"Quick Create Wizard created {len(created_slots)} slots for employee {self.employee_id.name}.")
            except (ValidationError, UserError) as e:
                 # Attraper les erreurs de contraintes de base (ex: dates invalides post-calcul)
                raise UserError(_("Error creating planning shifts: %s", e))
            except Exception as e:
                _logger.error("Unexpected error during quick slot creation: %s", e, exc_info=True)
                raise UserError(_("An unexpected error occurred while creating shifts."))

        # --- Retourner une action pour voir les créneaux créés (optionnel) ---
        if created_slots:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Created Planning Shifts'),
                'res_model': 'planning.slot',
                'view_mode': 'list,form', # Adapter les vues disponibles (sans gantt en community)
                'domain': [('id', 'in', created_slots.ids)],
                'target': 'current', # Ou 'main' pour remplacer la vue courante
            }
        else:
            # Si rien n'a été créé (ne devrait pas arriver sauf erreur)
            return {'type': 'ir.actions.act_window_close'}