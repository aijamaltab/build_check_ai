"""Views для интерфейса (docs/synthetic_spec.md §6 и §7): position_status (светофор) и issues_view (issues + лист + влияние на бюджет).

Это views, а не таблицы: схема §7 не меняется. Пороги подставляются из config/rules.yaml при создании view
(create_views вызывается в конце каждого прогона), поэтому в SQL нет «зашитых» чисел.
Влияние на бюджет считает код (src/rules/checks.py) и хранит в staging_issues_ext; issues_view отдаёт его рядом с issues,
потому что формулы (средневзвешенная цена сметы, частичные суммы) в SQL нечитаемы.
"""


def create_views(conn, cfg: dict) -> None:
    rules = cfg["rules"]
    over = 100 + rules["volume_exceeded"]["tolerance_pct"]            # выше: красный по объёму
    under = 100 - rules["position_status"]["green_under_tolerance_pct"]   # ниже: жёлтый (работа идёт)
    issue_types = "'volume_exceeded', 'price_increase', 'missing_in_vor'"
    conn.executescript(f"""
DROP VIEW IF EXISTS position_status;
CREATE VIEW position_status AS
SELECT project_id, work_key, unit, plan_qty, fact_qty, pct,
       CASE WHEN has_issue = 1 OR pct > {over} THEN 'red'
            WHEN pct < {under} THEN 'yellow'
            ELSE 'green' END AS status,
       review_rows
FROM (
    SELECT project_id, work_key, unit, plan_qty, fact_qty, has_issue, review_rows,
           CASE WHEN plan_qty IS NULL OR plan_qty = 0 THEN NULL ELSE fact_qty * 100.0 / plan_qty END AS pct
    FROM (
        -- позиции ВОР: план и накопительный факт по актам, привязанным к этой позиции
        SELECT p.project_id AS project_id, p.final_work_key AS work_key, p.unit_norm AS unit, p.qty_sum AS plan_qty,
               COALESCE((SELECT SUM(a.qty_sum) FROM staging_match_groups a
                         WHERE a.doc_type = 'act' AND a.status = 'matched' AND a.matched_group_id = p.group_id), 0) AS fact_qty,
               EXISTS(SELECT 1 FROM issues i WHERE i.project_id = p.project_id AND i.work_key = p.final_work_key
                      AND i.issue_type IN ({issue_types})) AS has_issue,
               -- строки актов в состоянии ambiguous, у которых эта позиция среди кандидатов (требуют проверки)
               (SELECT COUNT(DISTINCT c.group_id) FROM staging_match_candidates c
                JOIN staging_match_groups a ON a.group_id = c.group_id
                WHERE c.candidate_group_id = p.group_id AND a.status = 'ambiguous') AS review_rows
        FROM staging_match_groups p WHERE p.doc_type = 'vor'
        UNION ALL
        -- позиции только в актах (absent): плана нет, issue missing_in_vor есть
        SELECT g.project_id, g.final_work_key, g.unit_norm, NULL, SUM(g.qty_sum), 1, 0
        FROM staging_match_groups g WHERE g.doc_type = 'act' AND g.status = 'absent'
        GROUP BY g.project_id, g.final_work_key, g.unit_norm
    )
);

DROP VIEW IF EXISTS issues_view;
CREATE VIEW issues_view AS
SELECT i.issue_id, i.project_id, i.work_key, i.issue_type, i.expected, i.actual, i.delta, i.delta_pct, i.severity,
       i.source_file, e.source_sheet, i.source_row, i.explanation,
       e.impact_som, e.impact_note, e.confidence, e.review_note, e.expected_text, e.actual_text, e.unit, e.mode
FROM issues i JOIN staging_issues_ext e ON e.issue_id = i.issue_id
ORDER BY e.impact_som IS NULL, e.impact_som DESC, i.issue_id;
""")
    conn.commit()
