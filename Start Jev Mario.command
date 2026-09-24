#!/bin/zsh
cd -- "${0:A:h}"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONUNBUFFERED=1
printf '%s\n' 'Jev Mario — TypeSafe直接接続・連続Skill制御' 'Jevの応答待ち中もゲームは進み、局所制御が操作を担当します。' '判断回数は無制限。停滞・Skill失敗でも続行し、死亡またはクリアで終了します。' 'Esc / Q: 終了。Restartボタン / R: 新しい試行。終了後も画面が残ります。' ''
.venv/bin/python -m typesafe_mario.cli play --policy direct --continuous-skills --display dashboard --until-game-over --interactive-session
jev_exit=$?
if (( jev_exit != 0 )); then
  printf '%s\n' '起動または接続でエラーが発生しました。上の表示を確認してください。'
else
  printf '%s\n' '' '検証が終了しました。終了理由・到達位置・ログの保存先は上に表示されています。' 'death: マリオ死亡 / clear: クリア / user_stop: 手動停止'
fi
printf '%s\n' 'Enterでこの実行を終了します。'
read -r
exit $jev_exit
