import os
from flask import Flask, request, send_from_directory, jsonify, session, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from uuid import uuid4
from datetime import datetime
from functools import wraps

# --- Configuração da Aplicação Flask ---
app = Flask(__name__, static_folder='public')

app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['COVERS_FOLDER'] = 'covers'

# Garante que as pastas de upload e covers existem e as cria se não existirem
# Isso é crucial para o ambiente de produção como o Render
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])
if not os.path.exists(app.config['COVERS_FOLDER']):
    os.makedirs(app.config['COVERS_FOLDER'])

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///library.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024 # Limite de 50MB para uploads

# CHAVE SECRETA: ESSENCIAL PARA SESSÕES!
# Use os.environ.get para pegar a chave do ambiente (Render) ou um valor padrão (local)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'uma_chave_secreta_muito_segura_e_aleatoria_para_o_termo_ux')

# Variáveis de ambiente para credenciais de admin
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123') # Troque isso em produção!

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
            'original_filename': self.original_filename,
            'cover_url': url_for('serve_cover', filename=self.cover_filename) if self.cover_filename else url_for('serve_cover', filename='placeholder_cover.png'),
            'read_url': url_for('serve_book', filename=self.filename)
        }

# Garante que as tabelas são criadas quando o app inicia, se não existirem
# Isso é executado ao carregar o módulo, o que o Gunicorn fará.
with app.app_context():
    db.create_all()

# --- Funções Auxiliares ---
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
        session['logged_in'] = False # Garante que a sessão não está logada em caso de falha
        return jsonify({'error': 'Nome de usuário ou senha incorretos.'}), 401

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('serve_login'))

@app.route('/library')
@login_required # Protege esta rota
def serve_library():
    return send_from_directory(app.static_folder, 'library.html')

@app.route('/upload-book', methods=['POST'])
@login_required # Protege esta rota
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
        book_file.save(book_path)

        cover_file = request.files.get('cover_file')
        cover_filename = None
        if cover_file and cover_file.filename != '':
            original_cover_filename = cover_file.filename
            unique_cover_filename = f"{uuid4()}_{original_cover_filename}"
            cover_path = os.path.join(app.config['COVERS_FOLDER'], unique_cover_filename)
            cover_file.save(cover_path)
            cover_filename = unique_cover_filename

        new_book = Book(
            title=request.form.get('title', original_filename),
            filename=unique_filename,
            original_filename=original_filename,
            cover_filename=cover_filename
        )
        db.session.add(new_book)
        db.session.commit()
        return jsonify({'message': 'Livro enviado com sucesso!', 'book': new_book.to_dict()}), 201
    return jsonify({'error': 'Erro desconhecido ao enviar o livro.'}), 500

@app.route('/books', methods=['GET'])
@login_required # Protege esta rota
def get_books():
    books = Book.query.order_by(Book.upload_date.desc()).all()
    return jsonify([book.to_dict() for book in books]), 200

@app.route('/read/<filename>')
@login_required # Protege esta rota
def serve_book(filename):
    # Proteção para evitar travessia de diretório
    if not os.path.isabs(filename) and os.path.abspath(os.path.join(app.config['UPLOAD_FOLDER'], filename)).startswith(os.path.abspath(app.config['UPLOAD_FOLDER'])):
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
    return "Acesso negado", 403 # Retorna 403 para acesso negado se o caminho não for seguro

@app.route('/covers/<filename>')
@login_required # Protege esta rota
def serve_cover(filename):
    # Proteção para evitar travessia de diretório
    if not os.path.isabs(filename) and os.path.abspath(os.path.join(app.config['COVERS_FOLDER'], filename)).startswith(os.path.abspath(app.config['COVERS_FOLDER'])):
        return send_from_directory(app.config['COVERS_FOLDER'], filename)
    try:
        return send_from_directory(app.config['COVERS_FOLDER'], filename)
    except Exception:
        # Serve uma imagem de placeholder se a capa não for encontrada ou houver erro
        return send_from_directory(app.static_folder, 'placeholder_cover.png')


# Rota para excluir um livro
@app.route('/delete-book/<int:book_id>', methods=['DELETE'])
@login_required # Protege esta rota
def delete_book(book_id):
    book_to_delete = Book.query.get(book_id)
    if not book_to_delete:
        return jsonify({'message': 'Livro não encontrado no banco de dados.'}), 404

    try:
        book_path = os.path.join(app.config['UPLOAD_FOLDER'], book_to_delete.filename)
        if os.path.exists(book_path):
            os.remove(book_path)
        
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

# Não execute app.run() em ambiente de produção (Render)
# O Gunicorn é responsável por iniciar o aplicativo
# if __name__ == '__main__':
#     app.run(debug=True)
