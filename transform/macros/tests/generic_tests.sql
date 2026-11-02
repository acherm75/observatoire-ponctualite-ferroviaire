{# Tests génériques maison (évite une dépendance à dbt_utils). #}

{% test between(model, column_name, min, max) %}
select * from {{ model }}
where {{ column_name }} is not null
  and ({{ column_name }} < {{ min }} or {{ column_name }} > {{ max }})
{% endtest %}

{% test non_negative(model, column_name) %}
select * from {{ model }} where {{ column_name }} < 0
{% endtest %}

{% test dbt_utils_unique_combination(model, columns) %}
select {{ columns | join(', ') }}, count(*) as n
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1
{% endtest %}
