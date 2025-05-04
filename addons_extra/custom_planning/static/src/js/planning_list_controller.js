/** @odoo-module **/

import { ListController } from "@web/views/list/list_controller";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";

patch(ListController.prototype, {
    setup() {
        super.setup();
        this.action = useService("action");
    },

    // Intercepter la création d'un enregistrement
    async _onCreateRecord(ev) {
        // Vérifier si le modèle actuel est celui que l'on veut modifier
        if (this.props.resModel === 'planning.slot') {
            // Empêcher l'action par défaut si nécessaire (peut ne pas être requis si on appelle notre action)
            // ev?.stopPropagation(); // Voir si utile

            // Déclencher l'action de notre wizard
            this.action.doAction('custom_planning.action_planning_quick_create_wizard', {
                // Passer des informations de contexte si besoin
                // context: this.props.context,
                // on_close: () => { /* Action après fermeture du wizard */ },
            });
        } else {
            // Pour tous les autres modèles, laisser le comportement par défaut
            await super._onCreateRecord(ev);
        }
    }
});