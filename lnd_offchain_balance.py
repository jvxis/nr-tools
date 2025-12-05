#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Calcula o lucro diário off-chain de um node Lightning usando a base do LNDg.

- Receita: forwards (gui_forwards.fee, sem inbound_fee)
- Custo: rebalances (gui_payments.fee com status = 2)
- Saída: base SQLite própria com consolidação diária.

Inclui relatórios: dia anterior e lucro mensal (últimos N meses).
"""

import argparse
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict


# ===================== CONFIGURAÇÃO ===================== #

LNDG_DB_PATH = Path("/home/admin/lndg/data/db.sqlite3")
PROFIT_DB_PATH = Path("/home/admin/offchain_profit.sqlite3")


# ===================== MODELOS ===================== #


@dataclass
class DailyProfit:
    iso_date: str        # "YYYY-MM-DD"
    display_date: str    # "dd/MM/yyyy"
    forwards_sat: int
    rebalances_sat: int
    profit_sat: int


# ===================== FUNÇÕES DE DB ===================== #


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Abre uma conexão SQLite com pragmas básicos."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_profit_db(conn: sqlite3.Connection) -> None:
    """Cria a tabela de consolidação diária se não existir."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS daily_offchain_profit (
            date           TEXT PRIMARY KEY,  -- dd/mm/yyyy
            iso_date       TEXT NOT NULL,     -- yyyy-mm-dd
            forwards_sat   INTEGER NOT NULL,
            rebalances_sat INTEGER NOT NULL,
            profit_sat     INTEGER NOT NULL,
            created_at     TEXT NOT NULL,
            updated_at     TEXT NOT NULL
        );
        """
    )
    conn.commit()


# ===================== QUERIES LNDG ===================== #


def _tz_shift_param(offset_hours: int) -> str:
    """Retorna string +X hours/-X hours para usar em DATETIME()."""
    return f"{offset_hours:+d} hours"


def fetch_daily_forwards(
    lndg_conn: sqlite3.Connection, tz_offset_hours: int
) -> Dict[str, int]:
    """
    Retorna um dict { 'YYYY-MM-DD': total_forwards_sat }.

    Usa gui_forwards: soma apenas fee por dia (sem inbound_fee).
    Aplica deslocamento de fuso antes de agrupar para evitar quebra em UTC.
    """
    query = """
        SELECT
            DATE(DATETIME(forward_date, :tz_shift)) AS d,
            COALESCE(SUM(fee), 0) AS total_forwards
        FROM gui_forwards
        GROUP BY DATE(DATETIME(forward_date, :tz_shift))
        ORDER BY d;
    """
    rows = lndg_conn.execute(
        query, {"tz_shift": _tz_shift_param(tz_offset_hours)}
    ).fetchall()
    result: Dict[str, int] = {}
    for row in rows:
        iso_date = row["d"]
        if iso_date is None:
            continue
        total = row["total_forwards"] or 0
        # fee / inbound_fee vêm como REAL, mas são sats inteiros na prática
        result[iso_date] = int(round(total))
    return result


def fetch_daily_rebalances(
    lndg_conn: sqlite3.Connection, tz_offset_hours: int
) -> Dict[str, int]:
    """
    Retorna um dict { 'YYYY-MM-DD': total_rebalances_sat }.

    Custo = fee de rebalances via gui_payments com status = 2.
    Aplica deslocamento de fuso antes de agrupar.
    """
    query = """
        SELECT
            DATE(DATETIME(creation_date, :tz_shift)) AS d,
            COALESCE(SUM(fee), 0) AS total_rebalances
        FROM gui_payments
        WHERE status = 2
        GROUP BY DATE(DATETIME(creation_date, :tz_shift))
        ORDER BY d;
    """
    rows = lndg_conn.execute(
        query, {"tz_shift": _tz_shift_param(tz_offset_hours)}
    ).fetchall()
    result: Dict[str, int] = {}
    for row in rows:
        iso_date = row["d"]
        if iso_date is None:
            continue
        total = row["total_rebalances"] or 0
        result[iso_date] = int(round(total))
    return result

# ===================== AGREGAÇÃO ===================== #


def build_daily_profit(
    forwards: Dict[str, int],
    rebalances: Dict[str, int],
) -> Dict[str, DailyProfit]:
    """
    Junta receita (forwards) e custo (rebalances) por data ISO (YYYY-MM-DD)
    e gera um dict { iso_date: DailyProfit }.
    """
    all_dates = set(forwards.keys()) | set(rebalances.keys())
    daily: Dict[str, DailyProfit] = {}

    for iso_date in sorted(all_dates):
        fwd = forwards.get(iso_date, 0)
        rbl = rebalances.get(iso_date, 0)
        profit = fwd - rbl

        dt = datetime.strptime(iso_date, "%Y-%m-%d")
        display_date = dt.strftime("%d/%m/%Y")

        daily[iso_date] = DailyProfit(
            iso_date=iso_date,
            display_date=display_date,
            forwards_sat=fwd,
            rebalances_sat=rbl,
            profit_sat=profit,
        )

    return daily


# ===================== RELATÓRIOS ===================== #


def _local_today(tz_offset_hours: int) -> date:
    return (datetime.now(timezone.utc) + timedelta(hours=tz_offset_hours)).date()


def _month_floor(d: date) -> date:
    return d.replace(day=1)


def _subtract_months(d: date, months: int) -> date:
    year = d.year
    month = d.month - months
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, d.day)


def aggregate_monthly(
    daily: Dict[str, DailyProfit],
    months: int,
    tz_offset_hours: int,
) -> Dict[str, Dict[str, int]]:
    """Soma lucro mensal para os últimos N meses (inclui o mês corrente)."""
    today_local = _local_today(tz_offset_hours)
    start_month = _subtract_months(_month_floor(today_local), months - 1)

    monthly: Dict[str, Dict[str, int]] = {}
    for dp in daily.values():
        dp_date = datetime.strptime(dp.iso_date, "%Y-%m-%d").date()
        if dp_date < start_month:
            continue
        key = dp_date.strftime("%Y-%m")
        bucket = monthly.setdefault(
            key, {"forwards_sat": 0, "rebalances_sat": 0, "profit_sat": 0}
        )
        bucket["forwards_sat"] += dp.forwards_sat
        bucket["rebalances_sat"] += dp.rebalances_sat
        bucket["profit_sat"] += dp.profit_sat

    return dict(sorted(monthly.items()))


def get_yesterday_profit(
    daily: Dict[str, DailyProfit], tz_offset_hours: int
) -> DailyProfit | None:
    """Retorna o lucro consolidado de ontem no fuso escolhido."""
    y_date = _local_today(tz_offset_hours) - timedelta(days=1)
    return daily.get(y_date.isoformat())


# ===================== PERSISTÊNCIA CONSOLIDADA ===================== #


def reset_profit_table(conn: sqlite3.Connection) -> None:
    """Limpa completamente a tabela de consolidação (modo full-rebuild)."""
    conn.execute("DELETE FROM daily_offchain_profit;")
    conn.commit()


def upsert_daily_profit(
    conn: sqlite3.Connection,
    daily_data: Dict[str, DailyProfit],
) -> None:
    """
    Insere todos os registros em daily_offchain_profit.

    Como estamos limpando a tabela antes, aqui é só INSERT simples.
    Se no futuro quiser incremental, dá para trocar por ON CONFLICT(date) DO UPDATE.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    rows_to_insert = [
        (
            dp.display_date,
            dp.iso_date,
            dp.forwards_sat,
            dp.rebalances_sat,
            dp.profit_sat,
            now,
            now,
        )
        for _, dp in sorted(daily_data.items())
    ]

    conn.executemany(
        """
        INSERT INTO daily_offchain_profit (
            date,
            iso_date,
            forwards_sat,
            rebalances_sat,
            profit_sat,
            created_at,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?);
        """,
        rows_to_insert,
    )
    conn.commit()


# ===================== MAIN ===================== #


def calculate_all_history(
    lndg_db_path: Path = LNDG_DB_PATH,
    profit_db_path: Path = PROFIT_DB_PATH,
    tz_offset_hours: int = -3,
) -> Dict[str, DailyProfit]:
    """
    Recalcula TODO o histórico de lucro off-chain e escreve na base própria.
    Retorna o dicionário {iso_date: DailyProfit}.
    """
    if not lndg_db_path.exists():
        raise FileNotFoundError(f"Base LNDg não encontrada em: {lndg_db_path}")

    lndg_conn = get_connection(lndg_db_path)
    profit_conn = get_connection(profit_db_path)

    try:
        init_profit_db(profit_conn)

        forwards = fetch_daily_forwards(lndg_conn, tz_offset_hours)
        rebalances = fetch_daily_rebalances(lndg_conn, tz_offset_hours)

        daily = build_daily_profit(forwards, rebalances)

        reset_profit_table(profit_conn)
        upsert_daily_profit(profit_conn, daily)

        return daily
    finally:
        lndg_conn.close()
        profit_conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Calcula o lucro diário off-chain (forwards - rebalances) usando a base do LNDg."
    )
    parser.add_argument(
        "--tz-offset",
        type=int,
        default=-3,
        help="Deslocamento em horas em relação ao UTC (ex.: -3 para Brasília).",
    )
    parser.add_argument(
        "--months",
        type=int,
        default=6,
        help="Quantidade de meses para o relatório mensal (inclui mês corrente).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    daily = calculate_all_history(tz_offset_hours=args.tz_offset)
    num_days = len(daily)

    print(f"[OK] Consolidação diária concluída para {num_days} dia(s).")
    print(f"    Base de origem: {LNDG_DB_PATH}")
    print(f"    Base de destino: {PROFIT_DB_PATH}")

    yesterday_dp = get_yesterday_profit(daily, args.tz_offset)
    if yesterday_dp:
        print(
            f"[D-1] {yesterday_dp.display_date}: "
            f"forwards={yesterday_dp.forwards_sat} sats, "
            f"rebalances={yesterday_dp.rebalances_sat} sats, "
            f"lucro={yesterday_dp.profit_sat} sats"
        )
    else:
        print("[D-1] Sem dados consolidados para ontem (sem forwards/rebalances).")

    monthly = aggregate_monthly(
        daily, months=args.months, tz_offset_hours=args.tz_offset
    )
    if monthly:
        print(f"Lucro mensal (últimos {args.months} meses):")
        for ym, bucket in monthly.items():
            print(
                f"  {ym}: forwards={bucket['forwards_sat']} sats, "
                f"rebalances={bucket['rebalances_sat']} sats, "
                f"lucro={bucket['profit_sat']} sats"
            )


if __name__ == "__main__":
    main()
