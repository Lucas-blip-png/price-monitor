# price-monitor

Bot de Telegram que monitora preços de produtos e avisa quando o valor cai. Também lê canais públicos de promoção e te manda os posts que interessam.

- **Lojas:** KaBuM!, Amazon BR, Mercado Livre (veja a nota abaixo) e qualquer site, informando o seletor CSS do preço.
- **Alertas:** quando o preço atinge o alvo ou cai X% (padrão 5%). Sem spam: só avisa de novo se o preço baixar mais ou subir e cair outra vez.
- **Promoções:** monitora canais públicos do Telegram e avisa os posts que casam com suas palavras-chave ou com os produtos que você acompanha.
- **Seguro:** só responde aos chats listados em `ALLOWED_CHAT_IDS`.

## Como usar

1. No Telegram, fale com o [@BotFather](https://t.me/BotFather), crie um bot e copie o token.
2. Descubra seu ID de chat com o [@userinfobot](https://t.me/userinfobot).
3. `cp .env.example .env` e preencha `TELEGRAM_TOKEN` e `ALLOWED_CHAT_IDS`.
4. Rode:

```
pip install .
python -m price_monitor
```

ou com Docker (o banco SQLite fica em `./data`):

```
docker compose up -d --build
```

## Comandos

| Comando | O que faz |
|---|---|
| *(colar um link)* ou `/add <url> [alvo] [css=<seletor>]` | começa a monitorar |
| `/list` · `/remove <id>` | lista / remove produtos |
| `/target <id> <valor>` | define o preço alvo |
| `/history <id>` | preço atual, mínimo, máximo e últimas mudanças |
| `/check` | força uma checagem agora |
| `/canal add\|remove\|list <@canal>` | canais públicos de promoção |
| `/palavra add\|remove\|list <termo>` | palavras-chave que disparam aviso |
| `/melhor <produto>` | as 5 ofertas mais baratas do produto, entre os posts dos canais (últimos 30 dias) e os seus produtos monitorados |

**Melhor promoção:** o bot guarda os posts dos canais com o preço extraído (valor depois de "por"; parcelas como "10x de R$ 199" são ignoradas). Quando um post casa com um produto que você monitora e custa menos que o preço atual dele, o aviso vem com 🔥 *mais barato que o seu preço atual*. O preço é uma heurística de texto: cupons e frete soltos no post podem enganar. Canais testados: `promobit`, `promocoes`, `ofertasdodia`, `gafanhotoapp`, `cuponomia`.

Site fora da lista? Use o seletor CSS do preço, por exemplo `/add https://loja.com/produto 200 css=span.preco`. Antes disso o bot tenta o JSON-LD da página.

## Rodar 24h num servidor gratuito (Oracle Cloud Always Free)

O bot só avisa com o PC desligado se rodar num servidor sempre ligado. A Oracle oferece uma VM gratuita permanente (exige cartão só para verificar a identidade).

1. Crie a conta em [cloud.oracle.com](https://cloud.oracle.com). Escolha a **região principal** com cuidado: não dá para trocar depois.
2. *Compute → Instances → Create instance*: imagem **Ubuntu 22.04**, shape `VM.Standard.E2.1.Micro` (Always Free, AMD). O `VM.Standard.A1.Flex` (ARM) também é gratuito, mas costuma estar sem capacidade. Baixe a chave SSH. Não precisa abrir portas além do SSH: o bot só faz conexões de saída.
3. Pare o bot local (`docker compose down`): dois bots com o mesmo token disputam as mensagens.
4. No PowerShell, na pasta do projeto: `.\deploy\deploy.ps1 -Server ubuntu@IP_DA_VM -Key C:\caminho\chave.key`. O script envia o código, o `.env` (permissão 600) e o banco, instala o Docker e sobe o container com `restart: unless-stopped`. Rode de novo para atualizar.
5. Log: `ssh -i chave ubuntu@IP "cd price-monitor && sudo docker compose logs -f"`.

**Atenção:** a Oracle pode recolher instâncias Always Free quase ociosas (uso de CPU muito baixo por 7 dias). Se acontecer, migre a conta para *Pay As You Go*: os recursos Always Free continuam sem custo.

## Limitações

- **Mercado Livre:** a API pública exige token e a página redireciona clientes HTTP para uma verificação de conta, então `/add` falha por padrão. Com um token de aplicação em `ML_ACCESS_TOKEN` a leitura via API é tentada (não testada). Os canais de promoção cobrem bem as ofertas do ML.
- **Amazon:** a página de produto funciona, mas pode pedir captcha com muitas requisições. O bot avisa e tenta de novo no próximo ciclo.
- **Canais:** só canais **públicos** com preview web (`t.me/s/<canal>`). Grupos privados exigiriam uma conta de usuário (Telethon), que ficou de fora.
- **WhatsApp:** não suportado (não há API oficial gratuita).
- Uso pessoal, com poucas requisições (2 s de intervalo por domínio). Respeite os termos de uso das lojas.

## Testes

```
pip install -e ".[dev]"
python -m pytest
```

No Windows, se `python` abrir a Microsoft Store, use `py`.
