$ErrorActionPreference = 'SilentlyContinue'
$s = (Get-Item build_log.txt).CreationTime
$m = ((Get-Date) - $s).TotalMinutes
$h = (Import-Csv output\has_heatmap\highlights.csv | Select-Object -Expand video_id -Unique).Count
$n = (Import-Csv output\no_heatmap\highlights.csv | Select-Object -Expand video_id -Unique).Count
$done = $h + $n
$rate = if ($m -gt 0) { $done / $m } else { 0 }
$eta = if ($rate -gt 0) { (1122 - $done) / $rate / 60 } else { 0 }
"Elapsed {0} min | Done {1}/1122 (heatmap {2}/804, uniform {3}/318) | {4}/min | ETA {5} h" -f `
  [math]::Round($m, 1), $done, $h, $n, [math]::Round($rate, 2), [math]::Round($eta, 1)
