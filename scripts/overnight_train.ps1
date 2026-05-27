# Overnight training script for Poky MCCFR.
# Lance HU NLHE 5M iters (~5-7h) puis 3-max 3M iters (~4-6h). Total ~10-13h.
# Checkpoints toutes les 250k iters → résilient aux crashs.
#
# USAGE :
#   1. Désactiver sleep : powercfg /change standby-timeout-ac 0
#   2. Brancher le laptop
#   3. Ouvrir un terminal PowerShell, lancer : .\scripts\overnight_train.ps1
#   4. GARDER LA FENÊTRE OUVERTE TOUTE LA NUIT
#
# Si Phase A crashe, Phase B se lance quand même (best-effort).
# En cas de crash, le dernier checkpoint /250k iters est conservé sur disque.

# Continue sur erreur (au lieu de Stop) pour que Phase B tourne même si A échoue
$ErrorActionPreference = "Continue"
$PYTHON = "C:\Users\poste113\Desktop\DEV\AN\Poky\.venv\Scripts\python.exe"
$LOG_DIR = "C:\Users\poste113\Desktop\DEV\AN\Poky\data\overnight"
New-Item -ItemType Directory -Path $LOG_DIR -Force | Out-Null

$startTime = Get-Date
Write-Output "=== Overnight training START : $startTime ==="
Write-Output "Phase A : HU NLHE 5M iters (~5-7h)"
Write-Output "Phase B : 3-max NLHE 3M iters (~4-6h)"
Write-Output "Total estimé : 9-13h"
Write-Output ""

# ==== Phase A : HU NLHE blueprint (5M iters) ====
Write-Output "[Phase A] HU NLHE 5M iters START"
$logA = Join-Path $LOG_DIR "phaseA_hu_5M.log"
$pklA = "C:\Users\poste113\Desktop\DEV\AN\Poky\data\blueprint_hu\overnight_5M.pkl"

& $PYTHON -m poky.training.mccfr_hunl `
    --iterations 5000000 `
    --log-every 50000 `
    --save-every 250000 `
    --save-path $pklA `
    *>&1 | Tee-Object -FilePath $logA

$endA = Get-Date
$durA = $endA - $startTime
Write-Output ""
Write-Output "[Phase A] FIN. Durée : $($durA.Hours)h$($durA.Minutes)m"
if (Test-Path $pklA) {
    $sizeA = (Get-Item $pklA).Length / 1MB
    Write-Output "[Phase A] Checkpoint final : $pklA ($([math]::Round($sizeA, 1)) MB)"
} else {
    Write-Output "[Phase A] WARN: pas de fichier final. Vérifier checkpoints intermédiaires."
}

# ==== Phase B : 3-max NLHE blueprint (3M iters) ====
Write-Output ""
Write-Output "[Phase B] 3-max NLHE 3M iters START"
$logB = Join-Path $LOG_DIR "phaseB_3max_3M.log"
$pklB = "C:\Users\poste113\Desktop\DEV\AN\Poky\data\blueprint_3max\overnight_3M.pkl"

& $PYTHON -m poky.training.mccfr_nmax `
    --num-players 3 `
    --iterations 3000000 `
    --log-every 50000 `
    --save-every 250000 `
    --save-path $pklB `
    *>&1 | Tee-Object -FilePath $logB

$endB = Get-Date
$durB = $endB - $endA
Write-Output ""
Write-Output "[Phase B] FIN. Durée : $($durB.Hours)h$($durB.Minutes)m"
if (Test-Path $pklB) {
    $sizeB = (Get-Item $pklB).Length / 1MB
    Write-Output "[Phase B] Checkpoint final : $pklB ($([math]::Round($sizeB, 1)) MB)"
}

# ==== Phase C : Eval auto rapide ====
Write-Output ""
Write-Output "[Phase C] Évaluation auto"
$logEval = Join-Path $LOG_DIR "eval_hu.log"
if (Test-Path $pklA) {
    & $PYTHON -m poky.cli.eval_blueprint `
        --model $pklA --hands 2000 --opponent heuristic `
        *>&1 | Tee-Object -FilePath $logEval
}

$total = (Get-Date) - $startTime
Write-Output ""
Write-Output "=== OVERNIGHT TRAINING END : $(Get-Date) ==="
Write-Output "Durée totale : $($total.Hours)h$($total.Minutes)m"
Write-Output ""
Write-Output "Logs    : $LOG_DIR"
Write-Output "Modèles :"
if (Test-Path $pklA) { Write-Output "  HU    : $pklA" }
if (Test-Path $pklB) { Write-Output "  3-max : $pklB" }
