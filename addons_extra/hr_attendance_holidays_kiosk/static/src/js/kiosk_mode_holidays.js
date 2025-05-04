/** @odoo-module **/

import { KioskMode } from '@hr_attendance/js/kiosk_mode';
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { Dialog } from "@web/core/dialog/dialog";
import { Component, useState, onWillStart } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";

// Composant pour la boîte de dialogue
class RequestTimeOffDialog extends Component {
    static template = "hr_attendance_holidays_kiosk.RequestTimeOffDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        employeeId: Number,
        employeeName: String,
        leaveTypes: Array,
        rpc: Function,
        notification: Function,
    };

    setup() {
        this.state = useState({
            leaveTypeId: null,
            startDate: new Date().toISOString().slice(0, 10), // Default to today
            endDate: new Date().toISOString().slice(0, 10),   // Default to today
            startTime: "09:00", // Example default start time
            endTime: "17:00",   // Example default end time
            reason: "",
            requestUnit: 'day', // Default request unit
        });
    }

    onChangeLeaveType(ev) {
        const selectedOption = ev.target.selectedOptions[0];
        this.state.leaveTypeId = parseInt(ev.target.value);
        this.state.requestUnit = selectedOption.dataset.requestUnit || 'day';
        // Peut-être ajuster les dates/heures par défaut en fonction du type ?
    }

    getDateTime(dateStr, timeStr) {
        // Combine date and time, return in UTC string for Odoo
        // Important: Handle timezones carefully if needed. Kiosk might be in different TZ.
        // For simplicity, using local date/time and hoping Odoo interprets correctly based on user TZ.
        // A more robust solution involves moment.js or luxon if complex TZ needed.
        const date = new Date(`${dateStr}T${timeStr || '00:00:00'}`);
        // Odoo RPC usually expects UTC datetime strings
         // Format 'YYYY-MM-DD HH:MM:SS'
        return date.toISOString().slice(0, 19).replace('T', ' ');
       // return odoo.fields.DateTime.prototype.value_to_remote(date); // Might need Odoo JS utils
    }

    async confirm() {
        if (!this.state.leaveTypeId || !this.state.startDate || !this.state.endDate) {
            this.props.notification.add(_t("Veuillez remplir tous les champs requis."), { type: 'danger' });
            return;
        }

        let date_from = this.getDateTime(this.state.startDate, this.state.requestUnit === 'hour' ? this.state.startTime : '00:00:00');
        let date_to = this.getDateTime(this.state.endDate, this.state.requestUnit === 'hour' ? this.state.endTime : '23:59:59');

         // Basic validation: end date must be after start date
        if (new Date(date_to) < new Date(date_from)) {
             this.props.notification.add(_t("La date de fin doit être postérieure à la date de début."), { type: 'danger' });
             return;
         }

        try {
            const result = await this.props.rpc('/hr_holidays/kiosk/request_time_off', {
                employee_id: this.props.employeeId,
                leave_type_id: this.state.leaveTypeId,
                date_from: date_from,
                date_to: date_to,
                name: this.state.reason,
            });

            if (result.success) {
                this.props.notification.add(
                    _t("Demande d'absence pour %s créée.", this.props.employeeName),
                    { type: 'success' }
                );
                this.props.close();
            } else {
                this.props.notification.add(result.error || _t("Échec de la création de la demande d'absence."), { type: 'danger' });
            }
        } catch (error) {
            console.error("RPC Error:", error);
            this.props.notification.add(_t("Une erreur technique est survenue."), { type: 'danger' });
        }
    }

    cancel() {
        this.props.close();
    }
}

// Patcher le composant KioskMode existant
patch(KioskMode.prototype, {
    setup() {
        super.setup();
        this.dialog = useService("dialog");
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.rpc = useService("rpc"); // Utiliser le service rpc standard
        this.leaveTypes = useState([]);
    },

    async willStart() {
        await super.willStart();
        await this._fetchLeaveTypes(); // Charger les types d'absence au démarrage
    },

     async _fetchLeaveTypes() {
         try {
            // Recherche des types de congés accessibles (simplifié : prend tous les types actifs)
            // Idéalement, filtrer selon les droits ou la politique de l'entreprise si nécessaire
             const types = await this.orm.searchRead(
                 'hr.leave.type',
                 [['requires_allocation', '=', 'no']], // Exemple: seulement types sans allocation nécessaire? Adaptez!
                // Ou simplement [['active', '=', true]] pour tous les types actifs.
                // Vous pourriez aussi avoir besoin de [['active', '=', true], ['employee_requests', '=', 'yes']] si ce champ existe
                 ['id', 'name', 'request_unit']
             );
             this.leaveTypes.splice(0, this.leaveTypes.length, ...types); // Met à jour le state réactif
         } catch (error) {
             console.error("Failed to fetch leave types:", error);
             this.notification.add(_t("Impossible de charger les types d'absence."), { type: 'danger' });
         }
     },

    // Ajouter le gestionnaire pour le nouveau bouton
    async onClickHolidaysButton() {
        if (!this.selectedEmployee) return;

         // Re-fetch leave types in case they changed, or rely on willStart fetch
         // await this._fetchLeaveTypes();

        if (!this.leaveTypes || this.leaveTypes.length === 0) {
             this.notification.add(_t("Aucun type d'absence n'est configuré ou accessible."), { type: 'warning' });
             return;
         }


        this.dialog.add(RequestTimeOffDialog, {
            employeeId: this.selectedEmployee.id,
            employeeName: this.selectedEmployee.name,
            leaveTypes: this.leaveTypes, // Passer les types chargés
            rpc: this.rpc, // Passer le service rpc
            notification: this.notification, // Passer le service notification
        });
    },

    // On doit peut-être surcharger la méthode qui affiche les actions pour lier notre fonction
    // Cela dépend fortement de l'implémentation exacte de KioskMode.
    // Ici, on suppose que le template XML ajoute simplement le bouton
    // et que le click est géré globalement ou via un t-on-click dans le template hérité.
    // Si le template d'origine utilise une fonction JS pour générer les boutons,
    // il faudra patcher cette fonction pour ajouter notre bouton et son handler.

    // Assurez-vous que l'événement click sur '.o_hr_attendance_holidays_button'
    // appelle bien this.onClickHolidaysButton()
    // Le plus simple est souvent d'ajouter t-on-click directement dans le XML hérité:
    // <button ... t-on-click="() => this.onClickHolidaysButton()" ...>
    // (Adaptation nécessaire si le contexte 'this' n'est pas direct)
     // Ou, si le template XML initial (hr_attendance.hr_attendance_kiosk_mode) rend
     // les boutons via une boucle ou une fonction, il faut patcher cette fonction.

    // Alternative : Lier l'événement dans le setup ou onMounted si nécessaire
     // Si le bouton est ajouté via XML pur comme dans l'exemple,
     // Odoo OWL peut nécessiter une liaison explicite si le t-on-click n'est pas dans le template du composant lui-même.
     // Une solution est de mettre un ID unique sur le bouton et d'ajouter un listener dans onMounted.
     // MAIS, le `t-on-click` dans l'extension XML (xpath) devrait fonctionner si le contexte est bon.
     // Ajustement potentiel dans le XML :
     /*
     <xpath expr="//div[hasclass('o_hr_attendance_kiosk_actions')]" position="inside">
          <button t-if="!attendance.check_out"
                  class="btn btn-warning btn-lg o_hr_attendance_holidays_button"
                  type="button"
                  t-on-click="() => component.onClickHolidaysButton()"> <!-- Notez component. -->
              <i class="fa fa-calendar-times-o me-2" aria-hidden="true"></i> Déclarer Absence
          </button>
     </xpath>
     */
     // 'component' est souvent le nom donné au composant dans les templates QWeb Owl. Vérifiez le template parent.

});