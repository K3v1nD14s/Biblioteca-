import os
from flask import Flask, request, send_from_directory, jsonify, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from uuid import uuid4
from datetime import datetime
from functools import wraps

# --- Configuração da Aplicação Flask ---
app = Flask(__name__, static_folder='public')

# Define os diretórios para uploads de livros e capas (armazenamento local)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['COVERS_FOLDER'] = 'covers'

# Garante que as pastas de upload e covers existem e as cria se não existirem
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])
if not os.path.exists(app.config['COVERS_FOLDER']):
    os.makedirs(app.config['COVERS_FOLDER'])

# Configuração do banco de dados SQLite (armazenamento local, não persistente no Render Free)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///library.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Limite máximo de tamanho para upload de arquivos (200 MB)
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024

# CHAVE SECRETA: ESSENCIAL PARA A SEGURANÇA DAS SESSÕES DO FLASK!
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'uma_chave_secreta_muito_segura_e_aleatoria_para_o_termo_ux_fallback_dev')

# Credenciais de ADMIN para login. EM PRODUÇÃO, SEMPRE USE VARIÁVEIS DE AMBIENTE.
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')

db = SQLAlchemy(app)

# --- Definição do Modelo do Banco de Dados ---
class Book(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.Text)
    # 'filename' agora armazena o nome do arquivo local
    filename = db.Column(db.Text, nullable=False)
    original_filename = db.Column(db.Text, nullable=False)
    # 'cover_filename' agora armazena o nome da capa local
    cover_filename = db.Column(db.Text)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        # Gera URLs para servir arquivos localmente via rotas Flask
        cover_url = url_for('serve_cover', filename=self.cover_filename) if self.cover_filename else url_for('static', filename='placeholder_cover.png')
        read_url = url_for('serve_book', filename=self.filename)

        return {
            'id': self.id,
            'title': self.title,
            'filename': self.filename,
            'original_filename': self.original_filename,
            'cover_url': cover_url,
            'read_url': read_url
        }

# Garante que as tabelas do banco de dados são criadas quando o aplicativo inicia.
with app.app_context():
    db.create_all()

# --- Decorador para rotas protegidas (exige login) ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session or not session['logged_in']:
            return redirect(url_for('serve_login'))
        return f(*args, **kwargs)
    return decorated_function

# --- Rotas da Aplicação ---

@app.route('/')
def serve_login():
    # Se o usuário já estiver logado, redireciona diretamente para a biblioteca
    if 'logged_in' in session and session['logged_in']:
        return redirect(url_for('serve_library'))
    # Caso contrário, serve o arquivo index.html da pasta 'public'
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/login', methods=['POST'])
def login():
    username = request.json.get('username')
    password = request.json.get('password')

    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        session['logged_in'] = True
        return jsonify({'message': 'Login bem-sucedido!'}), 200
    else:
        session['logged_in'] = False
        return jsonify({'error': 'Nome de usuário ou senha incorretos.'}), 401

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('serve_login'))

@app.route('/library')
@login_required
def serve_library():
    return send_from_directory(app.static_folder, 'library.html')

@app.route('/upload-book', methods=['POST'])
@login_required
def upload_book():
    if 'book_file' not in request.files:
        return jsonify({'error': 'Nenhum arquivo de livro selecionado.'}), 400
    book_file = request.files['book_file']
    if book_file.filename == '':
        return jsonify({'error': 'Nome de arquivo de livro inválido.'}), 400

    if book_file:
        original_filename = book_file.filename
        unique_filename = f"{uuid4()}_{original_filename}"
        book_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        
        cover_filename = None
        cover_file = request.files.get('cover_file')
        if cover_file and cover_file.filename != '':
            original_cover_filename = cover_file.filename
            unique_cover_filename = f"{uuid4()}_{original_cover_filename}"
            cover_path = os.path.join(app.config['COVERS_FOLDER'], unique_cover_filename)
            cover_file.save(cover_path) # Salva a capa localmente
            cover_filename = unique_cover_filename

        book_file.save(book_path) # Salva o livro localmente

        new_book = Book(
            title=request.form.get('title', original_filename.split('.')[0]),
            filename=unique_filename,
            original_filename=original_filename,
            cover_filename=cover_filename
        )
        db.session.add(new_book)
        db.session.commit()
        return jsonify({'message': 'Livro enviado com sucesso!', 'book': new_book.to_dict()}), 201
    return jsonify({'error': 'Erro desconhecido ao enviar o livro.'}), 500

@app.route('/books', methods=['GET'])
@login_required
def get_books():
    books = Book.query.order_by(Book.upload_date.desc()).all()
    return jsonify([book.to_dict() for book in books]), 200

# Rota para servir arquivos de livro (PDFs, etc.) do armazenamento local
@app.route('/read/<filename>')
@login_required
def serve_book(filename):
    # Proteção para evitar travessia de diretório
    base_dir = os.path.abspath(app.config['UPLOAD_FOLDER'])
    full_path = os.path.abspath(os.path.join(base_dir, filename))
    if not full_path.startswith(base_dir):
        return "Acesso negado", 403
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# Rota para servir arquivos de capa do armazenamento local
@app.route('/covers/<filename>')
@login_required
def serve_cover(filename):
    # Proteção para evitar travessia de diretório
    base_dir = os.path.abspath(app.config['COVERS_FOLDER'])
    full_path = os.path.abspath(os.path.join(base_dir, filename))
    if not full_path.startswith(base_dir):
        return "Acesso negado", 403
    try:
        return send_from_directory(app.config['COVERS_FOLDER'], filename)
    except Exception:
        # Serve uma imagem de placeholder se a capa específica não for encontrada
        return send_from_directory(app.static_folder, 'placeholder_cover.png')

@app.route('/delete-book/<int:book_id>', methods=['DELETE'])
@login_required
def delete_book(book_id):
    book_to_delete = Book.query.get(book_id)
    if not book_to_delete:
        return jsonify({'message': 'Livro não encontrado no banco de dados.'}), 404

    try:
        # Remove o arquivo do livro do armazenamento local
        book_path = os.path.join(app.config['UPLOAD_FOLDER'], book_to_delete.filename)
        if os.path.exists(book_path):
            os.remove(book_path)
        
        # Remove o arquivo da capa do armazenamento local
        if book_to_delete.cover_filename:
            cover_path = os.path.join(app.config['COVERS_FOLDER'], book_to_delete.cover_filename)
            if os.path.exists(cover_path):
                os.remove(cover_path)

        db.session.delete(book_to_delete)
        db.session.commit()

        return jsonify({'message': 'Livro excluído com sucesso!'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Erro ao excluir livro: {str(e)}'}), 500

# Este bloco é executado apenas quando o script é rodado diretamente (ex: python app.py).
# No Render, o Gunicorn é responsável por iniciar o aplicativo, então app.run() não é usado.
# if __name__ == '__main__':
#     app.run(debug=True)
