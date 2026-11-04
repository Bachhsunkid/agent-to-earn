#!/bin/sh
# Start Freqtrade in dry-run (default) or live mode, chosen by DRY_RUN in .env.
# config.rpc.json (Telegram, REST API) is loaded only here, so backtests never need secrets.
# Live mode adds config.live.json (real money, capped capital) and its own trade database.
set -eu

db=tradesv3.dryrun.sqlite
extra=""
if [ "${DRY_RUN:-true}" = "false" ]; then
  if [ -z "${FREQTRADE__EXCHANGE__KEY:-}" ] || [ -z "${FREQTRADE__EXCHANGE__SECRET:-}" ]; then
    echo "DRY_RUN=false needs BINANCE_KEY and BINANCE_SECRET in .env" >&2
    exit 1
  fi
  db=tradesv3.live.sqlite
  extra="--config /freqtrade/user_data/config.live.json"
fi
# The whitelist is generated (scripts/build_universe.py); a fresh clone starts from the example.
# Without user_data/universe.json the bot refuses every entry, so run `make universe` first.
[ -f /freqtrade/user_data/config.pairs.json ] ||
  cp /freqtrade/user_data/config.pairs.example.json /freqtrade/user_data/config.pairs.json
echo "starting freqtrade: DRY_RUN=${DRY_RUN:-true}, database $db"
# $extra is intentionally unquoted: it is empty or two arguments.
exec freqtrade trade \
  --logfile /freqtrade/user_data/logs/freqtrade.log \
  --db-url "sqlite:////freqtrade/user_data/$db" \
  --config /freqtrade/user_data/config.json \
  --config /freqtrade/user_data/config.rpc.json \
  $extra
