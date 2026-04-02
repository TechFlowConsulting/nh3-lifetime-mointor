# NH3 Lifetime System (v2)

Este projeto lê dados do banco **PostgreSQL** (dump Aurora) usando as tabelas existentes:
- `public.sensors`
- `public.sensor_readings`
- `public.calibrations` (histórico/ordens – não contém sensibilidade)
e cria tabelas auxiliares para análise/IA:

- `public.nh3_daily_agg` (agregação diária – reduz drasticamente o volume)
- `public.sensor_calibration_points` (pontos de calibração com **Sa%** inseridos por você)
- `public.sensor_clusters` (cluster por comportamento)

## 1) Configuração

1. Crie/ative venv
```bash
python -m venv .venv
source .venv/bin/activate

cmd + shift + P para escolher o compilador
```

2. Instale dependências
```bash
python -m pip install --upgrade pip setuptools wheel
pip install --only-binary=:all: -r requirements.txt
```

3. Configure DB
- copie `config/db.yaml.example` para `config/db.yaml` e preencha `user` e `password`.

## 2) Criar tabelas auxiliares
```bash
python -m scripts.create_aux_tables
```

## 3) Agregar dados (1 Hz -> diário)
```bash
python scripts/aggregate_daily.py --start 2025-01-01 --end 2025-02-01
```

## 4) Subir API
```bash
uvicorn app.main:app --reload
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level debug
```
Acesse: `http://127.0.0.1:8000/docs`
## 5) popular tabelas
```bash
python -m scripts.aggregate_daily --start 2025-11-01 --end 2025-12-01
```
## 6) Gráficos (VS Code)
```bash
python analysis/explore.py --sensor-id 1
```


Tut git 

criar o git ignore se nao houver
   crie o arquivo .gitignore
   cole nele o seguinte código 
   .venv/
   __pycache__/
   *.pyc
   .DS_Store
   .env
   .idea/
   .vscode/
git init
depois adicionar arquivos 
  git add .
criar commit
  git commit -m "Primeira versão NH3 Lifetime Monitor"
Verificar 
  git status
Enviar par agithub
  git remote -v
se nao retornar nem um código é porque ainda nao colocou o endereço do reposítório 
  git remote add origin https://github.com/TechFlowConsulting/nh3-lifetime-mointor.git
depois conferir se entrou 
  git remote -v
enviar 
  git push -u origin main

  futuros push do projeto 
    git remote add origin https://github.com/TechFlowConsulting/nh3-lifetime-mointor.git
    git branch -M main
    git push -u origin main