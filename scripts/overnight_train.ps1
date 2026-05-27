# Overnight training script for Poky MCCFR.
# Lance HU NLHE 5M iters (~8h) puis 3-max 3M iters (~5h).
# Total ~13h. Checkpoints toutes les 250k iters.
#
# Usage :
#   1. Désactiver sleep : powercfg /change standby-timeout-ac 0
#   2. Brancher le laptop
#   3. Lancer : .\scripts\overnight_train.ps1
#   4. Garder la fenêtre ouverte (ou utiliser Start-Process pour background)

$ErrorActionPreference = "Stop"
$PYTHON = "C:\Users\poste113\Desktop\DEV\AN\Poky\.venv\Scripts\python.exe"
$LOG_DIR = "C:\Users\poste113\Desktop\DEV\AN\Poky\data\overnight"
New-Item -ItemType Directory -Path $LOG_DIR -Force | Out-Null

$startTime = Get-Date
Write-Output "=== Overnight training START : $startTime ==="

# ==== Phase A : HU NLHE blueprint (5M iters, ~8h) ====
Write-Output "`n[Phase A] HU NLHE blueprint : 5M iterations"
$logA = Join-Path $LOG_DIR "phaseA_hu_5M.log"
& $PYTHON -m poky.training.mccfr_hunl `
    --iterations 5000000 `
    --log-every 250000 `
    --save-path "C:\Users\poste113\Desktop\DEV\AN\Poky\data\blueprint_hu\overnight_5M.pkl" `
    2>&1 | Tee-Object -FilePath $logA

$endA = Get-Date
Write-Output "[Phase A] Terminé. Durée : $($endA - $startTime)"

# ==== Phase B : 3-max NLHE blueprint (3M iters, ~5h) ====
Write-Output "`n[Phase B] 3-max NLHE blueprint : 3M iterations"
$logB = Join-Path $LOG_DIR "phaseB_3max_3M.log"
& $PYTHON -m poky.training.mccfr_nmax `
    --num-players 3 `
    --iterations 3000000 `
    --log-every 200000 `
    --save-path "C:\Users\poste113\Desktop\DEV\AN\Poky\data\blueprint_3max\overnight_3M.pkl" `
    2>&1 | Tee-Object -FilePath $logB

$endB = Get-Date
Write-Output "[Phase B] Terminé. Durée totale : $($endB - $startTime)"

# ==== Phase C : Eval rapide des 2 blueprints ====
Write-Output "`n[Phase C] Évaluation"
& $PYTHON -m poky.cli.eval_blueprint `
    --model "C:\Users\poste113\Desktop\DEV\AN\Poky\data\blueprint_hu\overnight_5M.pkl" `
    --hands 1000 `
    --opponent heuristic 2>&1 | Tee-Object -FilePath (Join-Path $LOG_DIR "eval_hu.log")

Write-Output "`n=== Overnight training END : $(Get-Date) ==="
Write-Output "Total : $((Get-Date) - $startTime)"
Write-Output ""
Write-Output "Checkpoints :"
Write-Output "  HU    : data\blueprint_hu\overnight_5M.pkl"
Write-Output "  3-max : data\blueprint_3max\overnight_3M.pkl"
