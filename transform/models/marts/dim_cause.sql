select code_cause, libelle_cause, responsable, ordre
from {{ ref('ref_causes') }}
