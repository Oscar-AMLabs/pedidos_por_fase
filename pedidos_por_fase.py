import requests
import pandas as pd
import plotly.graph_objects as go
import boto3
import os

from io import BytesIO
from flask import Flask, render_template, redirect, url_for
from dotenv import load_dotenv
from datetime import datetime, timedelta

app = Flask(__name__)

# Configurações do AWS S3
bucket_name = 'pedidos-por-fase-healthcheck'
s3_file_name = 'Relatório analitico por Fase (Novo BI).xlsx'

# Carregar variáveis de ambiente do arquivo .env
load_dotenv()

aws_access_key = os.getenv('AWS_ACCESS_KEY_ID')
aws_secret_key = os.getenv('AWS_SECRET_ACCESS_KEY')

s3 = boto3.client('s3', aws_access_key_id=aws_access_key, aws_secret_access_key=aws_secret_key)

def load_excel_from_s3(bucket, key):
    s3 = boto3.client('s3', aws_access_key_id=aws_access_key, aws_secret_access_key=aws_secret_key)
    response = s3.get_object(Bucket=bucket, Key=key)
    file_stream = response['Body']
    return pd.read_excel(BytesIO(file_stream.read()), sheet_name='Dados')

df = load_excel_from_s3(bucket_name, s3_file_name)

print(df.head())

# Dictionary to store phase IDs for each pipe
nomes_fases_pipes = {
    # E01 - Administrativo
    '301698136': ['01 - Confirmação de Serviço', '02 - Cadastro no Omie', '03 - Geração de boleto',
                  '04 - Conferir Conta PAGSEGURO', '05 - Criar Conta PAGSEGURO', '06 - Gerar Etiqueta',
                  '09 - Gerar contrato', '10 - Pagamento', '11 - Aguardando assinatura', '12- Gerar Nota Fiscal',
                  '13 - Confirmação de Etiqueta', '14 - Criar usuario SWAGGER'],  
    
    # E02 - Produção
    '301694301': ['13 - Montagem', '14 - Lançar S/N', '15 - Preparação',
                  '16 - Finalização', '17 - Checklist final', '18 - Aguardando Embalagem',
                  '19 - Liberado para retirada', '20 - Em rota de Entrega'],  
    
    # P8 - Pedidos - Supreme edition
    '303112056': ['1 - Pedidos P8', '2 - Aguardar Email P8', '3 - Verificar Email P8'],

    # Pedidos - NFC-e
    '302332974': ['01 - Vendas NFC-e', '02 - Suporte', '03 - Postman', '04 - Instalação do SAT',
                  '05 - Gerar CSC', '06 - Habilitar banco de dados'],
 
    # P7 - Troca de titularidade
    '303093742': ['1 - Vendas P7', '2 - Aguardar Email P7', '3 - Verificar Email P7'],

    # E04 - Pós-venda
    '302201339': ['Conclusão dos Treinamentos', 'Checklist de Qualidade e Satisfação', 'Sucesso da Inauguração D-7',
                  'Feedback Pós-Inauguração']
}

def pipefy_send(query):
    url = "https://api.pipefy.com/graphql"
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "authorization": "Bearer eyJhbGciOiJIUzUxMiJ9.eyJpc3MiOiJQaXBlZnkiLCJpYXQiOjE2OTMzMTE3NTgsImp0aSI6ImE0OGU0MjIxLTE5ODMtNDgyOC1hY2E0LTk3M2FjMDgxYjljZiIsInN1YiI6MzAyNDg4MjU2LCJ1c2VyIjp7ImlkIjozMDI0ODgyNTYsImVtYWlsIjoiY2Fpby5wYWdsaWFyYW5pQGFtbGFicy5jb20uYnIiLCJhcHBsaWNhdGlvbiI6MzAwMjcxMjAyLCJzY29wZXMiOltdfSwiaW50ZXJmYWNlX3V1aWQiOm51bGx9.amWFG4ywllqfP7AK8tYwEZ-Z8LlCrnnOe6UBjHxhq3GGOX9n3c8CU3QIAPoCd-4vRIaY2p35Gndrn9oMFnAy5g"
    }
    response = requests.post(url, json={"query": query}, headers=headers)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Erro na chamada da API do Pipefy: {response.status_code}\n\n")
        print(response.text)
        return None

def buscar_dados_pipefy(pipe_id):
    query = f'''query {{
      pipe(id: "{pipe_id}") {{
        phases {{
          id
          name
          cards_count
        }}
      }}
    }}'''
    response = pipefy_send(query)
    if response and 'data' in response and 'pipe' in response['data']:
        return response['data']['pipe']['phases']
    else:
        print("Erro ao buscar dados do Pipefy ou resposta inesperada.")
        return []

def processar_dados_pipefy(df, pipe_id):
    data = []
    for index, row in df.iterrows():
        date = row['Data']
        for phase in nomes_fases_pipes.get(pipe_id, []):
            if phase in df.columns:
                card_count = row[phase]
                if not pd.isna(card_count):
                    data.append({'data': date, 'fase': phase, 'quantidade': card_count})
                    print(f"Date: {date}, Phase: {phase}, Card Count: {card_count}")

    df_processed = pd.DataFrame(data)
    print(df_processed)
    df_processed['data'] = pd.to_datetime(df_processed['data']).dt.date
    return df_processed

def filtrar_dados_ultimos_cinco_dias(df):
    hoje = datetime.now().date()
    ultimos_cinco_dias = [hoje - timedelta(days=i) for i in range(5)]
    ultimos_cinco_dias.sort()  # Ordena as datas em ordem crescente
    return df[df['data'].isin(ultimos_cinco_dias)], ultimos_cinco_dias

def criar_graficos(df, titulo, ultimos_cinco_dias):
    fases = df['fase'].unique()
    fig = go.Figure()

    for fase in fases:
        df_fase = df[df['fase'] == fase]
        df_fase = df_fase.groupby('data').sum().reindex(ultimos_cinco_dias).fillna(method='ffill').reset_index()
        df_fase['data'] = pd.to_datetime(df_fase['data'])  # Garantindo que a coluna 'data' seja datetime

        fig.add_trace(go.Scatter(
            x=df_fase['data'].dt.strftime('%d %B'), 
            y=df_fase['quantidade'], 
            mode='lines+markers',
            name=fase,
            hoverinfo='text',
            text=[f"Date: {d.strftime('%d %B')}<br>Phase: {fase}<br>Count: {q}" for d, q in zip(df_fase['data'], df_fase['quantidade'])],
        ))

    # Adiciona a linha de meta no valor 10
    fig.add_trace(go.Scatter(
        x=[d.strftime('%d %B') for d in ultimos_cinco_dias],
        y=[10] * len(ultimos_cinco_dias),
        mode='lines',
        name='Meta',
        line=dict(color='black', dash='dash'),
    ))

    fig.update_layout(
        title=titulo,
        xaxis_title='Data',
        yaxis_title='Quantidade de Pedidos',
        xaxis=dict(type='category', categoryorder='array', categoryarray=[d.strftime('%d %B') for d in ultimos_cinco_dias]),
        legend_title='Fases',
        hovermode='x' 
    )

    return fig.to_html(full_html=False)

def criar_grafico_rota_entrega(df, fase, titulo, ultimos_cinco_dias):
    df_fase = df[df['fase'] == fase]
    df_fase = df_fase.groupby('data').sum().reindex(ultimos_cinco_dias).fillna(method='ffill').reset_index()
    df_fase['data'] = pd.to_datetime(df_fase['data'])  # Garantindo que a coluna 'data' seja datetime

    fig = go.Figure(data=[
        go.Bar(
            x=df_fase['data'].dt.strftime('%d %B'),
            y=df_fase['quantidade'],
            hoverinfo='none',  # Remove hoverinfo to show only colors
        ),
        go.Scatter(
            x=df_fase['data'].dt.strftime('%d %B'),
            y=[60] * len(df_fase),
            mode='lines',
            name='Meta',
            line=dict(color='black', dash='dash'),
        )
    ])

    fig.update_layout(
        title=titulo,
        xaxis_title='Data',
        yaxis_title='Quantidade de Pedidos',
        xaxis=dict(type='category', categoryorder='array', categoryarray=[d.strftime('%d %B') for d in df_fase['data']]),
        yaxis=dict(range=[0, 70]),  # Ajusta o eixo Y para mostrar a meta
        hovermode='x'
    )

    return fig.to_html(full_html=False)

@app.route('/')
def pedidos_por_fase():
    pipe_ids = {
        'E01 - Administrativo': '301698136',
        'E02 - Produção': '301694301',
        'P8 - Pedidos - Supreme edition': '303112056',
        'Pedidos - NFC-e': '302332974',
        'P7 - Troca de Titularidade': '303093742',
        'E04 - Pós-venda': '302201339'
    }
    
    graficos = {}
    
    # Load data from Excel file
    df = pd.read_excel(file_path, sheet_name='Dados')
    
    for titulo, pipe_id in pipe_ids.items():

        df_processed = processar_dados_pipefy(df, pipe_id)
        print(f"Dados processados para {titulo}:\n{df_processed}")  # Imprime os dados processados

        df_filtered, ultimos_cinco_dias = filtrar_dados_ultimos_cinco_dias(df_processed)
        print(f"Dados filtrados para os últimos cinco dias ({titulo}):\n{df_filtered}")  # Imprime os dados filtrados
        
        graficos[titulo] = criar_graficos(df_filtered, f'Quantidade de Pedidos por Fase ({titulo})', ultimos_cinco_dias)

    # Create the specific graph for "Em Rota de Entrega"
    df_processed = processar_dados_pipefy(df, '301694301')
    grafico_rota_entrega = criar_grafico_rota_entrega(df_processed, '20 - Em rota de Entrega', 'Quantidade de Pedidos - Em Rota de Entrega (E02 - Produção)', ultimos_cinco_dias)

    return render_template('pedidos_por_fase.html', graficos=graficos, grafico_rota_entrega=grafico_rota_entrega)

if __name__ == '__main__':
    app.run(debug=True)
