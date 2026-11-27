# Como isso funciona (e como chegamos aqui)

Documento de referência do projeto: o problema, como a causa foi encontrada, o que o
script altera byte a byte, como foi validado e quais são os limites. Escrito para
que dê para retomar o trabalho sem depender da conversa que o originou.

## 1. O problema

Treinos de força criados no **Garmin Connect** e enviados a um **Garmin Instinct Solar 2X**
têm esta forma: um exercício, descanso cronometrado, bloco repetido 3 vezes, e depois um
**descanso aberto** (o relógio espera o botão, para começar o próximo exercício).

```
ativo → descanso 30s → REPETIR 3x → descanso aberto (botão)
```

Comportamento indesejado: depois da 3ª série, o relógio ainda cumpre os 30s e só depois
mostra o descanso aberto. São **dois descansos seguidos**. O desejado é que a última
série do bloco pule o descanso cronometrado e vá direto ao descanso aberto.

O Garmin Connect tem essa opção ("pular último descanso", no passo de repetição). Mas
só funcionava nos treinos em que ela tinha sido ativada na interface; nos demais, ativar
um a um dá trabalho.

## 2. Formato dos arquivos

Os `.fit` de treino (`file_id.type = workout`) **não são atividades gravadas**: são
definições de treino, pequenos (1,5 a 4 KB). Não têm FC, GPS nem timestamps de execução.
Trazem:

- `workout`: nome, esporte (`training`), subesporte (`strength_training`), número de passos;
- `workout_step`: um registro por passo (exercício, descanso, repetição);
- `exercise_title`: nomes de exercícios em texto;
- `memo_glob`: textos longos das notas, em bytes.

Estrutura de um arquivo FIT (relevante aqui):

| Parte | Detalhe |
|---|---|
| Cabeçalho | 14 bytes; tamanho dos dados em `[4:8]` (little-endian), assinatura `.FIT` em `[8:12]`, CRC do cabeçalho em `[12:14]` |
| Registros | cada um começa com 1 byte de cabeçalho: bit 7 = timestamp comprimido, bit 6 = mensagem de definição |
| Definição | fixa, para um número local de mensagem, a lista de campos `(número, tamanho, tipo)` e a ordem dos bytes |
| Dados | os valores, na ordem da definição anterior |
| Rodapé | CRC-16 de todo o arquivo (header + dados), 2 bytes no final |

A mensagem global **27** é `workout_step`. Campos que importam:

| Campo | Nome | Valores usados |
|---|---|---|
| 254 | `message_index` | posição do passo |
| 1 | `duration_type` | `5` = aberto (botão), `6` = repetir até completar passos |
| 7 | `intensity` | `1` = rest (descanso) |
| **18** | *(não documentado)* | `0` / `1` |

## 3. Como a causa foi encontrada

1. Os passos de todos os treinos foram listados lado a lado. A estrutura
   (`ativo → descanso → repetir → descanso aberto`) era **idêntica** nos treinos que
   funcionam e nos que não funcionam.
2. Comparando todos os campos, inclusive os que o decodificador chama de `unknown_*`, só
   um campo mudava: o **`unknown_18` do passo de repetição**.
   - Treinos que se comportam como desejado: `unknown_18 = 1` em todas as repetições
     (exceto a última do treino, que não é seguida de nada, e fica em 0).
   - Treinos com o problema: `unknown_18 = 0` em todas.
3. Conclusão: o campo 18 do passo de repetição é a opção **"pular último descanso"**.
   Ela não está na documentação do SDK da Garmin. É uma dedução pelo comportamento
   observado, confirmada na prática (ver seção 5).

Dica de armadilha: no `fitdecode`, `frame.get_value('unknown_18')` **não** encontra o
campo (devolve o fallback). É preciso percorrer `frame.fields` e comparar o `name`.

## 4. O que o script faz

`fit_skip_last_rest.py` abre o arquivo como bytes, percorre os registros FIT (sem depender
de nenhuma biblioteca), e para cada passo `duration_type == 6` (repetir) **seguido** de um
passo `duration_type == 5` com `intensity == 1` (descanso aberto):

1. escreve `1` no byte do campo 18 do passo de repetição;
2. depois de todas as alterações, **recalcula o CRC-16 do arquivo** e grava nos 2 últimos
   bytes; se o cabeçalho tem 14 bytes, recalcula também o CRC do cabeçalho (`[12:14]`);
3. grava num arquivo temporário e troca pelo original com `os.replace` (atômico).

Decisões de projeto:

- **Idempotente**: repetições que já estão em 1 não são tocadas. Rodar duas vezes não muda
  nada e a segunda execução diz "já estava correto".
- **Só altera o que precisa**: apenas repetições seguidas de descanso aberto. A última
  repetição do treino fica como está.
- **Dois motivos para pular, com mensagens separadas**: "já estava correto" e "não tem
  descanso aberto após as repetições (nada a corrigir)".
- **Substitui o original** (mesmo nome). Há `-b` para guardar `.bak` e `-n` para só simular.
- **Pasta atual por padrão**: sem argumentos, processa os `.fit`/`.FIT` da pasta.
- Tratamento de timestamps comprimidos, campos de desenvolvedor e ordem dos bytes
  (little/big-endian) do formato FIT.

## 5. Validação

- O arquivo gerado foi decodificado de novo com `fitdecode` (que valida o CRC): a lista de
  passos ficou idêntica à do original, mudando apenas os `unknown_18`.
- Só 12 bytes diferem do original: 10 flags + 2 de CRC (no exemplo testado).
- **Teste real no relógio**: o treino corrigido passou a ir direto para o descanso aberto
  após a última série do bloco, exatamente como os treinos que já vinham com a opção.
- O script final foi comparado com o resultado do patch manual: saída **idêntica byte a byte**.

## 6. Limites e cuidados

- O **campo 18 não é documentado**. Se a Garmin mudar o formato, isso pode parar de
  funcionar ou, no pior caso, ser ignorado. Teste em um arquivo antes de aplicar em todos.
- Treinos **sem descanso aberto** entre os exercícios (o relógio emenda um no outro) não
  são alterados: a opção só existe quando há um descanso aberto depois da repetição.
  Resolver isso exige inserir passos novos (reindexar todos os passos e atualizar
  `num_valid_steps`), o que o script **não** faz.
- Treinos com série "aberta" (`duration_type = open` no passo ativo) foram ligados pelo
  script, mas o comportamento no relógio **não foi testado**.
- Reenviar o treino pelo Garmin Connect pode regravar o arquivo e desfazer a alteração; a
  correção vale para o arquivo `.fit` copiado manualmente para o relógio.
- Os campos `exercise_category` / `exercise_name` que o Garmin grava às vezes não batem
  com o nome real do exercício; confie nas notas e nos `exercise_title`.

## 7. Privacidade

Os `.fit` contêm dados pessoais (nomes e notas dos treinos, número de série da conta).
Por isso **nunca são versionados**: o `.gitignore` ignora `*.fit`, `*.FIT` e `.Intervals/`.
Este repositório contém só o script e a documentação.

## 8. Como inspecionar um `.fit` sozinho

```bash
python3 -m venv v && ./v/bin/pip install fitdecode
./v/bin/python - <<'EOF'
import sys, fitdecode
with fitdecode.FitReader("treino.fit") as f:
    for fr in f:
        if fr.frame_type == fitdecode.FIT_FRAME_DATA and fr.name == "workout_step":
            print({x.name: x.value for x in fr.fields if x.value is not None})
EOF
```

Procure `duration_type: repeat_until_steps_cmplt` e confira o `unknown_18`.
