import os
from flask import Flask, request, send_from_directory, jsonify, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from uuid import uuid4
from datetime import datetime
from functools import wraps

# --- Configuração da Aplicação Flask ---
app = Flask(__name__, static_folder='public')

# Configuração para o Render:
# Use a variável de ambiente PORT fornecida pelo Render, ou 5173 como fallback para desenvolvimento local.
# app.config['PORT'] = int(os.environ.get('PORT', 5173)) # Não é necessário definir isso no config, o Gunicorn cuidará da porta.

app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['COVERS_FOLDER'] = 'covers'

# Para produção no Render, use uma variável de ambiente para a URI do banco de dados,
# se estiver usando PostgreSQL ou outro DB externo.
# Para SQLite, 'sqlite:///library.db' é ok se você entender que os dados serão efêmeros
# no Render Free Tier (se o disco não for persistente) ou se você tiver um plano com disco persistente.
# Se você for usar um banco de dados externo como PostgreSQL no Render,
# DESCOMENTE e ajuste a linha abaixo, usando a variável de ambiente DATABASE_URL
# app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///library.db')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///library.db' # Mantido para SQLite conforme seu setup

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

# CHAVE SECRETA: ESSENCIAL PARA SESSÕES!
# Em produção, esta chave DEVE ser gerada aleatoriamente e armazenada em uma variável de ambiente.
# Exemplo: app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'fallback_secreto_para_desenvolvimento')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'uma_chave_secreta_muito_segura_e_aleatoria_para_o_termo_ux')

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

# --- Decorador para rotas protegidas ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session or not session['logged_in']:
            return redirect(url_for('serve_login'))
        return f(*args, **kwargs)
    return decorated_function

# --- Rotas da API e Servidor de Conteúdo ---

@app.route('/')
def serve_login():
    if 'logged_in' in session and session['logged_in']:
        return redirect(url_for('serve_library'))
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    # Use variáveis de ambiente para credenciais em produção!
    # Exemplo: ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME')
    #          ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD')
    # Para o propósito deste teste, manteremos as fixas, mas é crucial mudar em produção.
    admin_username = os.environ.get('ADMIN_USERNAME', 'Admin')
    admin_password = os.environ.get('ADMIN_PASSWORD', 'Admin')


    if username == admin_username and password == admin_password:
        session['logged_in'] = True
        return jsonify({'message': 'Login bem-sucedido!'}), 200
    else:
        session['logged_in'] = False
        return jsonify({'error': 'Usuário ou senha inválidos.'}), 401

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('serve_login'))

@app.route('/library')
@login_required
def serve_library():
    return send_from_directory(app.static_folder, 'library.html')

@app.route('/upload', methods=['POST'])
@login_required
def upload_book():
    book_file = request.files.get('bookFile')
    cover_file = request.files.get('coverFile')
    title = request.form.get('title')

    if not book_file:
        return jsonify({'error': 'Nenhum arquivo de livro enviado.'}), 400

    if not book_file.filename.lower().endswith(('.pdf', '.epub', '.mobi', '.txt', '.doc', '.docx')):
        return jsonify({'error': 'Formato de livro não permitido.'}), 400
    if cover_file and not cover_file.filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')):
        return jsonify({'error': 'Formato de capa não permitido.'}), 400

    # Certifique-se de que os diretórios de upload existem
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['COVERS_FOLDER'], exist_ok=True)

    book_ext = os.path.splitext(book_file.filename)[1]
    unique_book_filename = str(uuid4()) + book_ext
    book_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_book_filename)

    cover_filename = None
    if cover_file:
        cover_ext = os.path.splitext(cover_file.filename)[1]
        cover_filename = str(uuid4()) + cover_ext
        cover_path = os.path.join(app.config['COVERS_FOLDER'], cover_filename)

    if not title or title.strip() == '':
        title = os.path.splitext(book_file.filename)[0]
    if not title or title.strip() == '': # Caso o nome do arquivo também seja vazio/apenas espaços
        title = None

    try:
        book_file.save(book_path)
        if cover_file:
            cover_file.save(cover_path)

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
        if os.path.exists(book_path):
            os.remove(book_path)
        if cover_filename and os.path.exists(cover_path):
            os.remove(cover_path)
        db.session.rollback()
        return jsonify({'error': f'Erro ao salvar livro: {str(e)}'}), 500

@app.route('/books', methods=['GET'])
@login_required
def get_books():
    books = Book.query.order_by(Book.upload_date.desc()).all()
    return jsonify([book.to_dict() for book in books]), 200

@app.route('/read/<path:filename>', methods=['GET'])
@login_required
def read_book(filename):
    # A verificação de caminho absoluto é uma boa prática de segurança.
    # Certifique-se de que o filename não tenta acessar diretórios fora de UPLOAD_FOLDER.
    base_dir = os.path.abspath(app.config['UPLOAD_FOLDER'])
    full_path = os.path.abspath(os.path.join(base_dir, filename))
    if not full_path.startswith(base_dir):
        return "Acesso negado", 403
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/covers/<path:filename>', methods=['GET'])
def get_cover(filename):
    base_dir = os.path.abspath(app.config['COVERS_FOLDER'])
    full_path = os.path.abspath(os.path.join(base_dir, filename))
    if not full_path.startswith(base_dir):
        return "Acesso negado", 403
    try:
        return send_from_directory(app.config['COVERS_FOLDER'], filename)
    except Exception:
        # Garante que 'public' exista e 'placeholder_cover.png' esteja lá
        return send_from_directory('public', 'placeholder_cover.png')

@app.route('/delete-book/<int:book_id>', methods=['DELETE'])
@login_required
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

# --- Ponto de Entrada da Aplicação ---
if __name__ == '__main__':
    with app.app_context():
        # Cria os diretórios de upload e covers se não existirem
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        os.makedirs(app.config['COVERS_FOLDER'], exist_ok=True)
        db.create_all() # Cria as tabelas (se não existirem)

    # Para Render, você usará o Gunicorn.
    # Esta parte (app.run) é principalmente para desenvolvimento local.
    # O Render espera que seu arquivo Procfile defina como iniciar o Gunicorn.
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5173)))
