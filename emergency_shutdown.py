import subprocess
import time
from datetime import datetime, timedelta
import os

# Para você utilizar este script você deve escolher quais máquinas monitorar, sempre é recomendável pingar um dispositivo local e um na rede externa evitando o risco-local. 
# Depois deve cronometrar o tempo de duração dos seu nobreak, a primeira checagem (crontab) normalmente deve ser feito em 1/3 do tempo do nobreak e a segunda checagem deve ser feito em um intervalo menor que o peimeiro para evitar com que as checagens fiquem programadas para após o termino da bateria.
# Para automatizar a checagem, deve-se criar um ambiente virtual e automatizar pelo uso do crontab.
# Linha a ser adicionada no Crontab para checagem a cada 30 minutos.
# crontab -e -> e adicione ao final do aqrquivo:
# */30 * * * * /home/admin/nr-tools/myenv/bin/python /home/admin/nr-tools/monitor.py
# Substitua "admin" pelo seu usuário.

# Configurações dos IPs para monitoramento
machine_ip = "192.203.230.10"  # Substitua pelo IP da máquina que deseja monitorar.
google_ip = "8.8.8.8"

second_check = 900  # 15 minutos para a segunda checagem

# Detecta automaticamente o usuário atual para configurar o caminho do log
user = os.getenv("USER") or os.getenv("USERNAME")
log_path = f"/home/{user}/nr-tools/power_monitor.log"

def check_connection(ip):
    """Função para checar conexão com o IP fornecido usando ping."""
    response = subprocess.call(['ping', '-c', '1', ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return response == 0  # Retorna True se conectado, False se desconectado

def monitor_and_shutdown():
    """Função principal para monitorar a conexão e desligar em caso de falha contínua."""
    machine_status = check_connection(machine_ip)
    internet_status = check_connection(google_ip)
    
    # Define o timestamp para o log com ajuste de UTC-3
    timestamp = (datetime.now() - timedelta(hours=3)).strftime("%d/%m/%Y %H:%M:%S")
    
    # Verifica se o arquivo de log existe, caso contrário, cria o arquivo
    if not os.path.exists(log_path):
        open(log_path, 'w').close()
    
    # Loga o status inicial da conexão
    with open(log_path, "a") as log_file:
        log_file.write(f"{timestamp} - Status inicial - Máquina: {'Online' if machine_status else 'Offline'}, Internet: {'Online' if internet_status else 'Offline'}\n")

    # Caso ambos estejam offline, inicia segunda checagem após intervalo de 15 minutos
    if not machine_status and not internet_status:
        time.sleep(second_check)

        # Verificação após a espera
        machine_status = check_connection(machine_ip)
        internet_status = check_connection(google_ip)
        
        timestamp = (datetime.now() - timedelta(hours=3)).strftime("%d/%m/%Y %H:%M:%S")
        with open(log_path, "a") as log_file:
            log_file.write(f"{timestamp} - Status após espera - Máquina: {'Online' if machine_status else 'Offline'}, Internet: {'Online' if internet_status else 'Offline'}\n")

        # Se ambos ainda estiverem offline, tentar desligamento
        if not machine_status and not internet_status:
            try:
                with open(log_path, "a") as log_file:
                    log_file.write(f"{timestamp} - Tentativa de desligamento acionada devido à falta de conexão.\n")
                
                shutdown_response = subprocess.call(['sudo', '/sbin/shutdown', '-h', 'now'])
                
                # Loga o sucesso ou falha do comando de desligamento
                with open(log_path, "a") as log_file:
                    if shutdown_response == 0:
                        log_file.write(f"{timestamp} - Comando de desligamento executado com sucesso.\n")
                    else:
                        log_file.write(f"{timestamp} - Falha ao executar o comando de desligamento. Código de retorno: {shutdown_response}\n")

            except Exception as e:
                with open(log_path, "a") as log_file:
                    log_file.write(f"{timestamp} - Erro ao tentar desligar: {str(e)}\n")
    else:
        # Loga "Conexão ativa" se não houver problemas de conexão
        with open(log_path, "a") as log_file:
            log_file.write(f"{timestamp} - Conexão ativa\n")

if __name__ == '__main__':
    # Cria o diretório para o log caso ele não exista
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    monitor_and_shutdown()
