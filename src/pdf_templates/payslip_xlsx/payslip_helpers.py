import calendar
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Sequence


@dataclass
class PayslipDayEntry:
    day: int
    am_worked: bool = False
    pm_worked: bool = False
    ot_hours: Decimal = Decimal(0)


def _safe_currency(value: Decimal) -> Decimal:
    try:
        return Decimal(value)
    except Exception:
        return Decimal(0)


def _ensure_31_days(
    entries: Sequence[PayslipDayEntry], year: int, month: int
) -> List[PayslipDayEntry]:
    """Return a full list of day entries (1..last_day) filling missing with blanks."""

    last_day = calendar.monthrange(year, month)[1]
    day_to_entry: Dict[int, PayslipDayEntry] = {
        e.day: e for e in entries if 1 <= e.day <= last_day
    }
    full: List[PayslipDayEntry] = []
    for d in range(1, last_day + 1):
        full.append(day_to_entry.get(d, PayslipDayEntry(day=d)))
    return full


# Normalize day entries to dataclass
def _as_entry(obj: Any) -> PayslipDayEntry:
    # Already a dataclass
    if isinstance(obj, PayslipDayEntry):
        return obj

    # AttendanceRecord-like object
    if (
        hasattr(obj, "attendance_date")
        and hasattr(obj, "morning")
        and hasattr(obj, "afternoon")
    ):
        day_num: int
        d = getattr(obj, "attendance_date")
        try:
            day_num = int(getattr(d, "day"))
        except Exception:
            day_num = 0
        raw_ot = getattr(obj, "ot", 0)
        try:
            ot_val = Decimal(raw_ot or 0)
        except Exception:
            ot_val = Decimal(0)
        return PayslipDayEntry(
            day=day_num,
            am_worked=bool(getattr(obj, "morning")),
            pm_worked=bool(getattr(obj, "afternoon")),
            ot_hours=ot_val,
        )

    # Dict-like inputs (support both legacy and attendance_model keys)
    if isinstance(obj, dict):
        # Day
        day_num = int(obj.get("day") or 0)
        if not day_num:
            ad = obj.get("attendance_date") or obj.get("date") or obj.get("date_str")
            try:
                if hasattr(ad, "day"):
                    day_num = int(ad.day)
                elif isinstance(ad, str) and ad:
                    from datetime import datetime as _dt

                    day_num = _dt.fromisoformat(ad).day
            except Exception:
                day_num = 0

        # Booleans
        am = bool(obj.get("am") or obj.get("am_worked") or obj.get("morning"))
        pm = bool(obj.get("pm") or obj.get("pm_worked") or obj.get("afternoon"))

        # OT
        raw_ot = obj.get("ot") if "ot" in obj else obj.get("ot_hours", 0)
        try:
            ot_val = Decimal(raw_ot or 0)
        except Exception:
            ot_val = Decimal(0)

        return PayslipDayEntry(day=day_num, am_worked=am, pm_worked=pm, ot_hours=ot_val)

    # Fallback empty entry
    return PayslipDayEntry(day=0)


def _as_decimal(value: Decimal | float | int | str) -> Decimal:
    try:
        return Decimal(value)
    except Exception:
        return Decimal(0)


def industry_scheme_mpf_per_day(
    daily_relevant_income: Decimal | float | int | str, over_65: bool
) -> tuple[Decimal, Decimal]:
    """Return per-day (employee, employer) MPF amounts for the Construction/Engineering
    Industry Scheme based on the provided table.

    Table (daily relevant income → fixed contribution for each side):
    - < $280: employer $10, employee $0
    - $280 ≤ x < $350: $15 / $15
    - $350 ≤ x < $450: $20 / $20
    - $450 ≤ x < $550: $25 / $25
    - $550 ≤ x < $650: $30 / $30
    - $650 ≤ x < $750: $35 / $35
    - $750 ≤ x < $850: $40 / $40
    - $850 ≤ x < $950: $45 / $45
    - ≥ $950: $50 / $50 (cap)
    """

    income = _as_decimal(daily_relevant_income)

    brackets = [
        (Decimal("0"), Decimal("280"), Decimal("0"), Decimal("10")),
        (Decimal("280"), Decimal("350"), Decimal("15"), Decimal("15")),
        (Decimal("350"), Decimal("450"), Decimal("20"), Decimal("20")),
        (Decimal("450"), Decimal("550"), Decimal("25"), Decimal("25")),
        (Decimal("550"), Decimal("650"), Decimal("30"), Decimal("30")),
        (Decimal("650"), Decimal("750"), Decimal("35"), Decimal("35")),
        (Decimal("750"), Decimal("850"), Decimal("40"), Decimal("40")),
        (Decimal("850"), Decimal("950"), Decimal("45"), Decimal("45")),
    ]

    if over_65 is True:
        brackets.append(
            (Decimal("1000"), Decimal("1000"), Decimal("0"), Decimal("0"))
        )  # if age is over 65, mpf is 0

    for lower, upper, emp, empr in brackets:
        if income >= lower and income < upper:
            return (emp, empr)

    # Cap at $50 each for ≥ $950 (and treat extremely high income as capped)
    return (Decimal("50"), Decimal("50"))


def _calculate_employee_mpf_total(
    day_entries: List[PayslipDayEntry],
    base_daily_salary: Decimal,
    over_65: bool,
    hourly_rate: Decimal,
) -> Decimal:
    """Calculate total employee MPF by summing daily MPF amounts for each worked day."""
    total_employee_mpf = Decimal("0")

    for entry in day_entries:
        # Only calculate MPF for days where worker actually worked (AM, PM, or overtime)
        if entry.am_worked or entry.pm_worked or entry.ot_hours > 0:
            daily_total_income = _calculate_daily_total_income(
                entry, base_daily_salary, hourly_rate
            )

            per_day_emp, _ = industry_scheme_mpf_per_day(daily_total_income, over_65)
            total_employee_mpf += per_day_emp

    return total_employee_mpf.quantize(Decimal("0.00"))


def _calculate_employer_mpf_total(
    day_entries: List[PayslipDayEntry],
    base_daily_salary: Decimal,
    over_65: bool,
    hourly_rate: Decimal,
) -> Decimal:
    """Calculate total employer MPF by summing daily MPF amounts for each worked day."""
    total_employer_mpf = Decimal("0")

    for entry in day_entries:
        # Only calculate MPF for days where worker actually worked (AM, PM, or overtime)
        if entry.am_worked or entry.pm_worked or entry.ot_hours > 0:
            daily_total_income = _calculate_daily_total_income(
                entry, base_daily_salary, hourly_rate
            )

            _, per_day_empr = industry_scheme_mpf_per_day(daily_total_income, over_65)
            total_employer_mpf += per_day_empr

    return total_employer_mpf.quantize(Decimal("0.00"))


def _calculate_daily_total_income(
    entry: PayslipDayEntry, base_daily_salary: Decimal, hourly_rate: Decimal
) -> Decimal:
    """Calculate total daily income including base salary and overtime."""
    daily_base_income = _calculate_daily_base_income(entry, base_daily_salary)
    daily_ot_income = _calculate_daily_overtime_income(entry, hourly_rate)

    return daily_base_income + daily_ot_income


def _calculate_daily_base_income(
    entry: PayslipDayEntry, base_daily_salary: Decimal
) -> Decimal:
    """Calculate base daily income based on work attendance."""
    # Check if any work was done (AM, PM, or overtime)
    if entry.am_worked or entry.pm_worked or entry.ot_hours > 0:
        worked_halves = int(entry.am_worked) + int(entry.pm_worked)

        if worked_halves >= 2:
            # Full day worked - full base salary
            return base_daily_salary
        elif worked_halves == 1:
            # Half day worked - half base salary
            return base_daily_salary / 2
        else:
            return Decimal("0")
    else:
        # No work done at all
        return Decimal("0")


def _calculate_daily_overtime_income(
    entry: PayslipDayEntry, hourly_rate: Decimal
) -> Decimal:
    """Calculate overtime income for the day."""
    if entry.ot_hours > 0:
        return _safe_currency(entry.ot_hours) * hourly_rate
    return Decimal("0")


def _each_worker_income_calculation(
    *,
    year: int,
    month: int,
    day_entries: Sequence[PayslipDayEntry] | Sequence[Dict[str, Any]] = (),
    base_daily_salary: Decimal,
    over_65: bool = False,
    hourly_rate: Decimal,
):

    num_days = calendar.monthrange(year, month)[1]

    normalized_entries: List[PayslipDayEntry] = [
        _as_entry(item) for item in day_entries
    ]

    normalized_entries = _ensure_31_days(normalized_entries, year, month)

    full_days = Decimal("0")
    half_days = Decimal("0")
    total_ot_hours = Decimal("0")
    for idx, entry in enumerate(normalized_entries, start=1):
        if idx > num_days:
            break
        worked_halves = int(entry.am_worked) + int(entry.pm_worked)
        if worked_halves >= 2:
            full_days += 1
        elif worked_halves == 1:
            half_days += 1
        total_ot_hours += entry.ot_hours

    equivalent_days = full_days + Decimal("0.5") * half_days

    employee_mpf_amount = _calculate_employee_mpf_total(
        normalized_entries, _safe_currency(base_daily_salary), over_65, hourly_rate
    )
    employer_mpf_amount = _calculate_employer_mpf_total(
        normalized_entries, _safe_currency(base_daily_salary), over_65, hourly_rate
    )

    ot_salary_total = _safe_currency(total_ot_hours) * hourly_rate

    daily_salary = _safe_currency(base_daily_salary) * equivalent_days

    real_salary = (
        daily_salary
        + _safe_currency(ot_salary_total)
        - _safe_currency(employee_mpf_amount)
    ).quantize(
        Decimal("0.00")
    )  # shizhijine

    total_payment = (
        daily_salary
        + _safe_currency(ot_salary_total)
        + _safe_currency(employer_mpf_amount)
    ).quantize(
        Decimal("0.00")
    )  # zong jin e

    return {
        "full_days": full_days,
        "half_days": half_days,
        "equivalent_days": equivalent_days,
        "ot_hours": total_ot_hours,
        "base_daily_salary": _safe_currency(base_daily_salary),
        "daily_salary": daily_salary,
        "ot_salary": ot_salary_total,
        "employee_mpf_amount": employee_mpf_amount,
        "employer_mpf_amount": employer_mpf_amount,
        "real_salary": real_salary,
        "total_payment": total_payment,
    }
