"""Создание сделок в amoCRM из отчёта по мероприятию.

Примеры:
  python main.py "отчет.xlsx" --preview            # только показать, что будет создано
  python main.py "отчет.xlsx" --limit 1 --step     # первая сделка, с паузой перед каждым «Сохранить»
  python main.py "отчет.xlsx"                      # создать все
  python main.py --probe                           # выгрузить поля формы новой сделки в logs/probe.txt
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from excel_reader import read_deals, progress_key

import paths

PROGRESS = paths.PROGRESS_FILE


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def save_progress(progress: dict):
    PROGRESS.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")


def print_preview(deals, progress, pipeline):
    print(f"\nНайдено сделок: {len(deals)}\n")
    for i, d in enumerate(deals, 1):
        mark = "  (уже создана — пропуск)" if progress_key(progress, d.name, pipeline) in progress else ""
        if d.red: mark += " (красная строка — пропуск)"
        elif d.refused: mark += " (возможный отказ)"
        print(f"{i:>3}. [{d.sheet}, стр.{d.row}] {d.name}{mark}")
        for c in d.contacts:
            print(f"       {c.role}: {c.name or '—'} | тел: {c.phone_field or '—'}")
    print()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Создание сделок в amoCRM из xlsx-отчёта")
    ap.add_argument("xlsx", nargs="?", help="путь к файлу отчёта .xlsx")
    ap.add_argument("--sheet", action="append", help="обработать только этот лист (можно несколько раз)")
    ap.add_argument("--school", default="", help="название школы, если в файле не указано")
    ap.add_argument("--preview", action="store_true", help="только показать сделки, браузер не открывать")
    ap.add_argument("--limit", type=int, default=0, help="создать не больше N сделок")
    ap.add_argument("--step", action="store_true", help="пауза перед каждым «Сохранить» для проверки")
    ap.add_argument("--yes", action="store_true", help="не спрашивать подтверждение")
    ap.add_argument("--probe", action="store_true", help="диагностика формы новой сделки")
    ap.add_argument("--pipeline", default="", help="воронка amoCRM")
    args = ap.parse_args()

    cfg = paths.load_config()
    base_url = cfg.get("amo_url", "").strip()
    progress = load_json(PROGRESS, {})

    if args.probe:
        if not base_url:
            print("Укажите amo_url в config.json")
            return 1
        from amo_bot import AmoBot
        bot = AmoBot(base_url)
        bot.start()
        try:
            bot.ensure_logged_in()
            print("Поля формы записаны в", bot.probe())
            input("Проверьте браузер. Enter — закрыть (сделка НЕ сохраняется)...")
        finally:
            bot.stop()
        return 0

    if not args.xlsx:
        ap.print_help()
        return 1

    deals, warnings = read_deals(args.xlsx, args.sheet, args.school)
    print_preview(deals, progress, args.pipeline)
    for w in warnings:
        print("! ", w)
    todo = [d for d in deals if not d.red and progress_key(progress, d.name, args.pipeline) not in progress]
    if args.limit:
        todo = todo[: args.limit]

    if args.preview:
        return 0
    if not todo:
        print("Нечего создавать.")
        return 0
    if not base_url:
        print("Укажите amo_url в config.json (например https://yourcompany.amocrm.ru)")
        return 1
    if not args.yes:
        ans = input(f"\nСоздать {len(todo)} сделок в {base_url}? [да/нет]: ").strip().lower()
        if ans not in ("да", "д", "y", "yes"):
            print("Отменено.")
            return 0

    from amo_bot import AmoBot
    bot = AmoBot(base_url, step=args.step, slow_mo=cfg.get("slow_mo_ms", 150))
    bot.start()
    ok = 0
    try:
        bot.ensure_logged_in()
        for n, d in enumerate(todo, 1):
            print(f"[{n}/{len(todo)}] {d.name} ...", end=" ", flush=True)
            try:
                url = bot.create_deal(d, args.pipeline)
            except Exception as e:  # noqa: BLE001
                if getattr(e, "uncertain_save", False):
                    url = bot.deal_url() if not bot.closed and "/leads/detail/" in bot.page.url else None
                    progress[progress_key(progress, d.name, args.pipeline)] = {"status": "uncertain", "url": url}
                    save_progress(progress)
                    print("Результат сохранения нужно проверить в amoCRM. Повтор заблокирован.")
                    return 2
                shot = bot.screenshot(f"error-{d.name}")
                print(f"ОШИБКА: {e}\n    скриншот: {shot}\n    текущая страница: {bot.page.url}")
                if "/leads/detail/" in bot.page.url:
                    # сделка уже сохранена, но, возможно, без второго контакта — помечаем, чтобы не задвоить
                    progress[progress_key(progress, d.name, args.pipeline)] = {"url": bot.page.url, "status": "partial", "error": str(e),
                                       "at": time.strftime("%Y-%m-%d %H:%M")}
                    save_progress(progress)
                    print("    сделка помечена как partial — проверьте её вручную")
                print("Остановлено. После исправления запустите снова — созданные сделки будут пропущены.")
                return 2
            progress[progress_key(progress, d.name, args.pipeline)] = {"url": url, "status": "ok", "at": time.strftime("%Y-%m-%d %H:%M")}
            save_progress(progress)
            ok += 1
            print("ok", url)
    finally:
        print(f"\nСоздано: {ok} из {len(todo)}")
        if args.step or ok < len(todo):
            input("Enter — закрыть браузер...")
        bot.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
