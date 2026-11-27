#!/usr/bin/env python3
"""Ativa "pular último descanso" nos treinos .fit da Garmin.

Em cada passo "Repetir", se o passo seguinte for um descanso aberto (apertar
o botão), liga a flag `unknown_18` (campo 18 do workout_step). Assim a última
série do bloco pula o descanso cronometrado e vai direto para o descanso aberto.

O arquivo original é SUBSTITUÍDO por uma versão corrigida com o mesmo nome.
A gravação é atômica (arquivo temporário + troca), então uma falha no meio
não deixa o original corrompido.

Uso:
    ./fit_skip_last_rest.py                              # todos os .fit da pasta atual
    ./fit_skip_last_rest.py pasta/                       # todos os .fit de outra pasta
    ./fit_skip_last_rest.py treino.fit [outro.fit ...]   # só estes arquivos
    ./fit_skip_last_rest.py -n *.fit                     # só mostra o que mudaria
    ./fit_skip_last_rest.py -b treino.fit                # guarda treino.fit.bak

Só usa a biblioteca padrão.
"""
import argparse
import os
import shutil
import struct
import sys
from pathlib import Path

MSG_WORKOUT_STEP = 27
F_DURATION_TYPE, F_INTENSITY, F_SKIP_LAST_REST, F_MESSAGE_INDEX = 1, 7, 18, 254
DUR_OPEN, DUR_REPEAT_UNTIL_STEPS = 5, 6
INTENSITY_REST = 1

_CRC = [0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
        0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400]


def crc16(data, crc=0):
    for x in data:
        tmp = _CRC[crc & 0xF]
        crc = ((crc >> 4) & 0x0FFF) ^ tmp ^ _CRC[x & 0xF]
        tmp = _CRC[crc & 0xF]
        crc = ((crc >> 4) & 0x0FFF) ^ tmp ^ _CRC[(x >> 4) & 0xF]
    return crc


def read_steps(b):
    """Percorre os registros FIT e devolve os workout_steps com offsets."""
    hs = b[0]
    if bytes(b[8:12]) != b".FIT":
        raise ValueError("não é um arquivo FIT")
    end = hs + struct.unpack("<I", b[4:8])[0]
    defs, steps, i = {}, [], hs
    while i < end:
        h = b[i]; i += 1
        if h & 0x80:                                   # timestamp comprimido
            i += defs[(h >> 5) & 3]["size"]
            continue
        lt = h & 0x0F
        if h & 0x40:                                   # definição
            i += 1
            little = b[i] == 0; i += 1
            g = struct.unpack("<H" if little else ">H", b[i:i + 2])[0]; i += 2
            n = b[i]; i += 1
            fields, off = {}, 0
            for _ in range(n):
                fields[b[i]] = (off, b[i + 1]); off += b[i + 1]; i += 3
            if h & 0x20:                               # campos de desenvolvedor
                m = b[i]; i += 1
                for _ in range(m):
                    off += b[i + 1]; i += 3
            defs[lt] = {"g": g, "fields": fields, "size": off, "little": little}
        else:                                          # dados
            d = defs[lt]
            if d["g"] == MSG_WORKOUT_STEP:
                f = d["fields"]
                get = lambda n: b[i + f[n][0]] if n in f else None
                steps.append({
                    "dur": get(F_DURATION_TYPE),
                    "int": get(F_INTENSITY),
                    "flag_off": i + f[F_SKIP_LAST_REST][0] if F_SKIP_LAST_REST in f else None,
                    "idx": int.from_bytes(
                        b[i + f[F_MESSAGE_INDEX][0]:i + f[F_MESSAGE_INDEX][0] + 2],
                        "little" if d["little"] else "big") if F_MESSAGE_INDEX in f else len(steps),
                })
            i += d["size"]
    return steps, end


def patch(data):
    """Devolve (bytes novos, lista de índices alterados, motivo se nada mudou)."""
    b = bytearray(data)
    steps, end = read_steps(b)
    changed, sem_campo, alvos = [], False, 0
    for k in range(len(steps) - 1):
        s, nxt = steps[k], steps[k + 1]
        if s["dur"] != DUR_REPEAT_UNTIL_STEPS:
            continue
        if nxt["dur"] == DUR_OPEN and nxt["int"] == INTENSITY_REST:
            alvos += 1
            if s["flag_off"] is None:
                sem_campo = True
            elif b[s["flag_off"]] != 1:
                b[s["flag_off"]] = 1
                changed.append(s["idx"])
    if not changed:
        if sem_campo:
            return None, [], "o arquivo não tem o campo 18 nos passos de repetição"
        if alvos == 0:
            return None, [], "não tem descanso aberto após as repetições (nada a corrigir)"
        return None, [], "já estava correto"
    struct.pack_into("<H", b, end, crc16(b[:end]))
    if b[0] >= 14:
        struct.pack_into("<H", b, 12, crc16(b[:12]))
    return bytes(b), changed, ""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", default=["."],
                    help="arquivos .fit ou pastas (padrão: a pasta atual)")
    ap.add_argument("-b", "--backup", action="store_true", help="guarda o original como .bak")
    ap.add_argument("-n", "--dry-run", action="store_true", help="não grava nada")
    args = ap.parse_args()

    files = []
    for p in map(Path, args.paths):
        files += sorted(f for f in p.iterdir() if f.suffix.lower() == ".fit") if p.is_dir() else [p]

    erros = 0
    for f in files:
        try:
            new, changed, why = patch(f.read_bytes())
        except Exception as e:
            print(f"ERRO  {f.name}: {e}"); erros += 1; continue
        if new is None:
            print(f"pulou {f.name}: {why}"); continue
        if args.dry_run:
            print(f"mudaria {f.name}: {len(changed)} repetições (passos {changed})"); continue
        if args.backup:
            shutil.copy2(f, f.with_suffix(f.suffix + ".bak"))
        tmp = f.with_name(f.name + ".tmp")
        tmp.write_bytes(new)
        shutil.copymode(f, tmp)
        os.replace(tmp, f)                      # troca atômica: o original deixa de existir
        print(f"ok    {f.name}: {len(changed)} repetições (passos {changed})")
    sys.exit(1 if erros else 0)


if __name__ == "__main__":
    main()
