{# Nom de gare normalisé pour les jointures : majuscules, sans accents ni tirets. #}
{% macro normalize_name(col) -%}
    upper(trim(regexp_replace(strip_accents({{ col }}), '[-\s]+', ' ', 'g')))
{%- endmacro %}
