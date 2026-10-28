<?php
// Sessões do Claude Code para o dashboard, lidas do estado local do J.A.R.V.I.S.
// para o Claude Code (~/.claude/jarvis/hud-sessions). Só responde para a própria máquina.
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

if (!in_array($_SERVER['REMOTE_ADDR'] ?? '', ['127.0.0.1', '::1'], true)) {
    http_response_code(403);
    echo json_encode(['erro' => 'só local']);
    exit;
}

// O Apache do XAMPP pode rodar como outro usuário, então o caminho tem padrão fixo.
$base = getenv('JARVIS_CC_DIR') ?: 'C:/Users/mathe/.claude/jarvis';
$dirSessoes = $base . '/hud-sessions';
if (!is_dir($dirSessoes)) {
    echo json_encode(['instalado' => false]);
    exit;
}

$titulos = json_decode(@file_get_contents($base . '/.titles.json') ?: '{}', true) ?: [];
$agora = time();
$inicioHoje = strtotime('today');
$sessoes = [];
$acoesHoje = 0;

foreach (glob($dirSessoes . '/*', GLOB_ONLYDIR) as $dir) {
    $id = basename($dir);
    $ultima = 0;
    foreach (['burst.txt', 'feed.txt', 'hb'] as $f) {
        if (is_file("$dir/$f")) $ultima = max($ultima, filemtime("$dir/$f"));
    }
    if (!$ultima || $agora - $ultima > 86400) continue;

    $feed = is_file("$dir/feed.txt") ? file("$dir/feed.txt", FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) : [];
    $eventos = [];
    foreach ($feed as $linha) {
        $p = explode("\t", $linha, 3);
        if (count($p) < 3) continue;
        $ts = (int) floor(((float) $p[0]) / 1000);
        if ($p[1] !== 'JVS' && $ts >= $inicioHoje) $acoesHoje++;
        $eventos[] = ['ts' => $ts, 'tipo' => $p[1], 'texto' => $p[2]];
    }

    if (is_file("$dir/end") || is_file("$dir/closed")) $status = 'encerrada';
    elseif ($agora - $ultima < 120) $status = 'trabalhando';
    else $status = 'parada';

    $sessoes[] = [
        'id' => substr($id, 0, 8),
        'titulo' => trim($titulos[$id]['title'] ?? '') ?: 'Sessão ' . substr($id, 0, 8),
        'modelo' => trim(@file_get_contents("$dir/model.txt") ?: ''),
        'status' => $status,
        'ultimaAtividade' => $ultima,
        'acoes' => count(array_filter($eventos, fn($e) => $e['tipo'] !== 'JVS')),
        'recentes' => array_slice(array_reverse($eventos), 0, 4),
    ];
}

usort($sessoes, fn($a, $b) => $b['ultimaAtividade'] <=> $a['ultimaAtividade']);

echo json_encode([
    'instalado' => true,
    'ativas' => count(array_filter($sessoes, fn($s) => $s['status'] === 'trabalhando')),
    'sessoes24h' => count($sessoes),
    'acoesHoje' => $acoesHoje,
    'mudo' => is_file($base . '/.mute'),
    'sessoes' => array_slice($sessoes, 0, 6),
], JSON_UNESCAPED_UNICODE);
