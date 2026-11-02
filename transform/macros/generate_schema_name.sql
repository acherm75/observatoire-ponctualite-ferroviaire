{# Utilise le nom de schéma tel quel (staging, marts…) au lieu de <cible>_<schéma>. #}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ custom_schema_name if custom_schema_name else target.schema }}
{%- endmacro %}
