# garmin-pular-descanso

Script para treinos de força `.fit` da Garmin: faz a última série de cada bloco
pular o descanso cronometrado e ir direto para o descanso aberto (apertar o botão).

## O problema

Em um treino `série → descanso 30s → repetir 3x → descanso aberto`, o relógio
cumpre os 30s depois da 3ª série e só então mostra o descanso aberto. São dois
descansos seguidos.

## O que o script faz

Em cada passo "Repetir" seguido de um descanso aberto, liga a opção
"pular último descanso" (campo 18 do `workout_step`, não documentado no SDK da
Garmin), e recalcula o CRC do arquivo. Só usa a biblioteca padrão do Python.

## Uso

```bash
./fit_skip_last_rest.py -n          # mostra o que mudaria, sem gravar
./fit_skip_last_rest.py             # corrige todos os .fit da pasta atual
./fit_skip_last_rest.py -b          # idem, guardando cada original como .bak
./fit_skip_last_rest.py treino.fit  # só um arquivo
```

**O arquivo original é substituído** (gravação atômica). Use `-b` para manter cópia.
Arquivos que já estão corretos, ou que não têm descanso aberto, são pulados.

## Limitações

- O campo 18 não é documentado: a função foi deduzida comparando treinos exportados
  do Garmin Connect, e testada em um Instinct Solar 2X.
- Treinos sem descanso aberto entre os exercícios não são alterados.

Os arquivos `.fit` são ignorados pelo `.gitignore` por conterem dados pessoais.
