import os
from flask import Flask, request, send_from_directory, jsonify, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from uuid import uuid4
from datetime import datetime
from functools import wraps

# --- Configuração da Aplicação Flask ---
app = Flask(__name__, static_folder='public')

# Define os diretórios para uploads de livros e capas
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['COVERS_FOLDER'] = 'covers'

# Configuração do banco de dados SQLAlchemy
# Usa uma variável de ambiente DATABASE_URL se disponível (para PostgreSQL no Render, por exemplo)
# Caso contrário, usa SQLite localmente.
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///library.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Limite máximo de tamanho para upload de arquivos (50 MB)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

# CHAVE SECRETA: ESSENCIAL PARA A SEGURANÇA DAS SESSÕES DO FLASK!
# Em produção, este valor DEVE ser definido como uma variável de ambiente no Render.
# O segundo argumento de os.environ.get é um valor padrão para desenvolvimento local,
# caso a variável de ambiente não esteja definida.
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'uma_chave_secreta_muito_segura_e_aleatoria_para_o_termo_ux_fallback_dev')

db = SQLAlchemy(app)

# --- Definição do Modelo do Banco de Dados ---
class Book(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.Text)
    filename = db.Column(db.Text, nullable=False)
    original_filename = db.Column(db.Text, nullable=False)
    cover_filename = db.Column(db.Text)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'filename': self.filename,
            'originalFilename': self.original_filename,
            'coverFilename': self.cover_filename,
            'uploadDate': self.upload_date.isoformat()
        }

# --- Decorador para rotas protegidas (exige login) ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Verifica se 'logged_in' está na sessão e é True
        if 'logged_in' not in session or not session['logged_in']:
            return redirect(url_for('serve_login')) # Redireciona para a página de login se não estiver logado
        return f(*args, **kwargs)
    return decorated_function

# --- Rotas da API e Servidor de Conteúdo ---

# Rota para servir a página de login (index.html) na raiz do aplicativo
@app.route('/')
def serve_login():
    # Se o usuário já estiver logado, redireciona diretamente para a biblioteca
    if 'logged_in' in session and session['logged_in']:
        return redirect(url_for('serve_library'))
    # Caso contrário, serve o arquivo index.html da pasta 'public'
    # CORREÇÃO AQUI: send_from_directory estava com "from" duplicado.
    return send_from_directory(app.static_folder, 'index.html')

# Rota para processar o formulário de login
@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    # Credenciais de ADMIN. EM PRODUÇÃO, SEMPRE USE VARIÁVEIS DE AMBIENTE.
    # O segundo argumento de os.environ.get é um valor padrão para desenvolvimento local.
    admin_username = os.environ.get('ADMIN_USERNAME', 'Admin_Fallback_Dev')
    admin_password = os.environ.get('ADMIN_PASSWORD', 'Admin_Fallback_Dev')

    if username == admin_username and password == admin_password:
        session['logged_in'] = True # Define a sessão como logada
        return jsonify({'message': 'Login bem-sucedido!'}), 200
    else:
        session['logged_in'] = False # Garante que não esteja logado
        return jsonify({'error': 'Usuário ou senha inválidos.'}), 401

# Rota para fazer logout
@app.route('/logout')
def logout():
    session.pop('logged_in', None) # Remove a variável de sessão 'logged_in'
    return redirect(url_for('serve_login')) # Redireciona para a página de login

# Rota para servir a página da biblioteca (protegida com login_required)
@app.route('/library')
@login_required # Esta linha PROTEGE a rota, exigindo que o usuário esteja logado
def serve_library():
    return send_from_directory(app.static_folder, 'library.html')

# Rota para upload de arquivos de livro e capa
@app.route('/upload', methods=['POST'])
@login_required # Protege esta rota também
def upload_book():
    book_file = request.files.get('bookFile')
    cover_file = request.files.get('coverFile')
    title = request.form.get('title')

    if not book_file:
        return jsonify({'error': 'Nenhum arquivo de livro enviado.'}), 400

    # Validação de formatos de arquivo
    if not book_file.filename.lower().endswith(('.pdf', '.epub', '.mobi', '.txt', '.doc', '.docx')):
        return jsonify({'error': 'Formato de livro não permitido.'}), 400
    if cover_file and not cover_file.filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')):
        return jsonify({'error': 'Formato de capa não permitido.'}), 400

    # Certifique-se de que os diretórios de upload existam.
    # 'exist_ok=True' evita erro se o diretório já existir.
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['COVERS_FOLDER'], exist_ok=True)

    # Gera um nome de arquivo único para o livro
    book_ext = os.path.splitext(book_file.filename)[1]
    unique_book_filename = str(uuid4()) + book_ext
    book_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_book_filename)

    cover_filename = None
    if cover_file:
        # Gera um nome de arquivo único para a capa
        cover_ext = os.path.splitext(cover_file.filename)[1]
        cover_filename = str(uuid4()) + cover_ext
        cover_path = os.path.join(app.config['COVERS_FOLDER'], cover_filename)

    # Usa o nome do arquivo original se o título não for fornecido
    if not title or title.strip() == '':
        title = os.path.splitext(book_file.filename)[0]

    try:
        book_file.save(book_path) # Salva o arquivo do livro
        if cover_file:
            cover_file.save(cover_path) # Salva o arquivo da capa

        # Cria uma nova entrada no banco de dados para o livro
        new_book = Book(
            title=title,
            filename=unique_book_filename,
            original_filename=book_file.filename,
            cover_filename=cover_filename
        )
        db.session.add(new_book)
        db.session.commit()

        return jsonify({
            'message': 'Livro e capa enviados com sucesso!',
            'title': title,
            'filename': unique_book_filename,
            'originalFilename': book_file.filename,
            'coverFilename': cover_filename
        }), 200
    except Exception as e:
        # Em caso de erro, tenta remover arquivos salvos e reverter a transação do banco de dados
        if os.path.exists(book_path):
            os.remove(book_path)
        if cover_filename and os.path.exists(cover_path):
            os.remove(cover_path)
        db.session.rollback()
        return jsonify({'error': f'Erro ao salvar livro: {str(e)}'}), 500

# Rota para listar todos os livros cadastrados
@app.route('/books', methods=['GET'])
@login_required # Protege esta rota
def get_books():
    books = Book.query.order_by(Book.upload_date.desc()).all()
    return jsonify([book.to_dict() for book in books]), 200

# Rota para servir o arquivo de livro para leitura/download
@app.route('/read/<path:filename>', methods=['GET'])
@login_required # Protege esta rota
def read_book(filename):
    # Garante que o arquivo solicitado está dentro do diretório de uploads para evitar Path Traversal
    base_dir = os.path.abspath(app.config['UPLOAD_FOLDER'])
    full_path = os.path.abspath(os.path.join(base_dir, filename))
    if not full_path.startswith(base_dir):
        return "Acesso negado", 403
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# Rota para servir arquivos de capa
@app.route('/covers/<path:filename>', methods=['GET'])
def get_cover(filename):
    # Garante que o arquivo solicitado está dentro do diretório de capas para evitar Path Traversal
    base_dir = os.path.abspath(app.config['COVERS_FOLDER'])
    full_path = os.path.abspath(os.path.join(base_dir, filename))
    if not full_path.startswith(base_dir):
        return "Acesso negado", 403
    try:
        return send_from_directory(app.config['COVERS_FOLDER'], filename)
    except Exception:
        # Se a capa específica não for encontrada, serve uma imagem de placeholder
        return send_from_directory('public', 'placeholder_cover.png')

# Rota para excluir um livro do banco de dados e do sistema de arquivos
@app.route('/delete-book/<int:book_id>', methods=['DELETE'])
@login_required # Protege esta rota
def delete_book(book_id):
    book_to_delete = Book.query.get(book_id)
    if not book_to_delete:
        return jsonify({'message': 'Livro não encontrado no banco de dados.'}), 404

    try:
        # Remove o arquivo do livro
        book_path = os.path.join(app.config['UPLOAD_FOLDER'], book_to_delete.filename)
        if os.path.exists(book_path):
            os.remove(book_path)
        
        # Remove o arquivo da capa, se existir
        if book_to_delete.cover_filename:
            cover_path = os.path.join(app.config['COVERS_FOLDER'], book_to_delete.cover_filename)
            if os.path.exists(cover_path):
                os.remove(cover_path)

        # Remove a entrada do livro do banco de dados
        db.session.delete(book_to_delete)
        db.session.commit()

        return jsonify({'message': 'Livro excluído com sucesso!'}), 200
    except Exception as e:
        db.session.rollback() # Reverte a transação do banco de dados em caso de erro
        return jsonify({'error': f'Erro ao excluir livro: {str(e)}'}), 500

# --- Ponto de Entrada da Aplicação ---
# Este bloco é executado apenas quando o script é rodado diretamente (ex: python app.py),
# não quando é iniciado pelo Gunicorn no Render.
if __name__ == '__main__':
    with app.app_context():
        # Cria os diretórios de upload e capas se não existirem
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        os.makedirs(app.config['COVERS_FOLDER'], exist_ok=True)
        db.create_all() # Cria as tabelas do banco de dados (se não existirem)

    # IMPORTANTE: A linha app.run() ABAIXO FOI REMOVIDA/COMENTADA!
    # No Render, o Gunicorn (configurado no Procfile) é quem inicia o aplicativo.
    # Manter app.run() ativo pode causar comportamento indesejado ou conflitos em produção.
    # app.run(debug=True, host='0.0.0.0', port=5173)
