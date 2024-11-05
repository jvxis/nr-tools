# Charge-LND Docker - Gestão de Max_HTLC
## Procedimento GERAL
No diretorio do usuario umbrel / admin ou qualquer outro que seja o que você utiliza
```
mkdir charge-lnd
```

```
cd charge-lnd
```

```
nano charge.config
```
Copiar o conteúdo
```
[default]

[0-mydefaults]
# no strategy, so this only sets some defaults
min_htlc_msat = 1000
max_htlc_msat_ratio = 1

[1)Acima de 99%]
chan.min_ratio = 0.99
strategy = static
max_htlc_msat_ratio = 0.99

[2)Entre 95% e 98,9%]
chan.max_ratio = 0.989
chan.min_ratio = 0.95
strategy = static
max_htlc_msat_ratio = 0.95

[3)Entre 90% e 94,9%]
chan.max_ratio = 0.949
chan.min_ratio = 0.90
strategy = static
max_htlc_msat_ratio = 0.90

[4)Entre 85% e 89,9%]
chan.max_ratio = 0.899
chan.min_ratio = 0.85
strategy = static
max_htlc_msat_ratio = 0.85

[5)Entre 80% e 84,9%]
chan.max_ratio = 0.849
chan.min_ratio = 0.80
strategy = static
max_htlc_msat_ratio = 0.80

[6)Entre 75% e 79,9%]
chan.max_ratio = 0.799
chan.min_ratio = 0.75
strategy = static
max_htlc_msat_ratio = 0.75

[7)Entre 70% e 74,9%]
chan.max_ratio = 0.749
chan.min_ratio = 0.70
strategy = static
max_htlc_msat_ratio = 0.70

[8)Entre 65% e 69,9%]
chan.max_ratio = 0.699
chan.min_ratio = 0.65
strategy = static
max_htlc_msat_ratio = 0.65

[9)Entre 60% e 64,9%]
chan.max_ratio = 0.649
chan.min_ratio = 0.60
strategy = static
max_htlc_msat_ratio = 0.60

[10)Entre 55% e 59,9%]
chan.max_ratio = 0.599
chan.min_ratio = 0.55
strategy = static
max_htlc_msat_ratio = 0.55

[11)Entre 50% e 54,9%]
chan.max_ratio = 0.549
chan.min_ratio = 0.50
strategy = static
max_htlc_msat_ratio = 0.50

[12)Entre 45% e 49,9%]
chan.max_ratio = 0.499
chan.min_ratio = 0.45
strategy = static
max_htlc_msat_ratio = 0.45

[13)Entre 40% e 44,9%]
chan.max_ratio = 0.449
chan.min_ratio = 0.40
strategy = static
max_htlc_msat_ratio = 0.40

[14)Entre 35% e 39,9%]
chan.max_ratio = 0.399
chan.min_ratio = 0.35
strategy = static
max_htlc_msat_ratio = 0.35

[15)Entre 30% e 34,9%]
chan.max_ratio = 0.349
chan.min_ratio = 0.30
strategy = static
max_htlc_msat_ratio = 0.30

[16)Entre 25% e 29,9%]
chan.max_ratio = 0.299
chan.min_ratio = 0.25
strategy = static
max_htlc_msat_ratio = 0.25

[17)Entre 20% e 24,9%]
chan.max_ratio = 0.249
chan.min_ratio = 0.20
strategy = static
max_htlc_msat_ratio = 0.20

[18)Entre 15% e 19,9%]
chan.max_ratio = 0.199
chan.min_ratio = 0.15
strategy = static
max_htlc_msat_ratio = 0.15

[19)Entre 10% e 14,9%]
chan.max_ratio = 0.149
chan.min_ratio = 0.10
strategy = static
max_htlc_msat_ratio = 0.10

[20)Entre 7% e 9,9%]
chan.max_ratio = 0.099
chan.min_ratio = 0.07
strategy = static
max_htlc_msat_ratio = 0.07

[21)Entre 5% e 6,9%]
chan.max_ratio = 0.069
chan.min_ratio = 0.05
strategy = static
max_htlc_msat_ratio = 0.05

[22)Entre 2,1% e 4,9%]
chan.max_ratio = 0.049
chan.min_ratio = 0.021
strategy = static
max_htlc_msat_ratio = 0.02

[23)HTLC - below 2%]
chan.max_ratio = 0.02
strategy = static
max_htlc_msat_ratio = 0.005
```
Sair e Salvar: CTRL+X teclar Y

## COMANDO para UMBREL (Atencao ao Diretorio)
O comando considera para o caso do umbrel, o usuário umbrel. Se o seu usuário for outro, alterar `/home/umbrel/umbrel` para `home/<seu_user>/umbrel`
```
docker run --name charge --rm -it --network=umbrel_main_network -e GRPC_LOCATION=10.21.21.9:10009 -e LND_DIR=/data/.lnd -e CONFIG_LOCATION=/app/charge.config -v /home/umbrel/umbrel/app-data/lightning/data/lnd:/data/.lnd -v /home/umbrel/charge-lnd/charge.config:/app/charge.config accumulator/charge-lnd:latest
```

## COMANDO para Standalone (Considera user Admin e Instalacao do lnd no /data/lnd)
```
docker run --name charge --rm -t -e GRPC_LOCATION=localhost:10009 -e LND_DIR=/data/.lnd -e CONFIG_LOCATION=/app/charge.config -v /data/lnd:/data/.lnd -v /admin/charge-lnd/charge.config:/app/charge.config accumulator/charge-lnd:latest
```
