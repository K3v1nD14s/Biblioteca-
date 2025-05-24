import os
from flask import Flask, request, send_from_directory, jsonify, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from uuid import uuid4
from datetime import datetime
from functools import wraps # Importar wraps aqui

# --- Configuração da Aplicação Flask ---
app = Flask(__name__, static_folder='public')

app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['COVERS_FOLDER'] = 'covers'

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///library.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

# CHAVE SECRETA: ESSENCIAL PARA SESSÕES!
# Esta chave deve ser uma string longa, aleatória e secreta em produção.
# Para este ambiente de desenvolvimento, esta é suficiente.
app.config['SECRET_KEY'] = 'uma_chave_secreta_muito_segura_e_aleatoria_para_o_termo_ux'

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
        # Verifica se 'logged_in' está na sessão e é True
        if 'logged_in' not in session or not session['logged_in']:
            return redirect(url_for('serve_login')) # Redireciona para a página de login se não estiver logado
        return f(*args, **kwargs)
    return decorated_function

# --- Rotas da API e Servidor de Conteúdo ---

# Rota para servir a página de login (index.html) na raiz
@app.route('/')
def serve_login():
    # Se já estiver logado, redireciona diretamente para a biblioteca
    if 'logged_in' in session and session['logged_in']:
        return redirect(url_for('serve_library'))
    # Caso contrário, serve a página de login
    return send_from_directory(app.static_folder, 'index.html')

# Rota para processar o formulário de login
@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    # Credenciais fixas de ADMIN para teste
    if username == 'Admin' and password == 'Admin':
        session['logged_in'] = True # Define a sessão como logada
        return jsonify({'message': 'Login bem-sucedido!'}), 200
    else:
        session['logged_in'] = False # Garante que não esteja logado
        return jsonify({'error': 'Usuário ou senha inválidos.'}), 401

# Rota para fazer logout
@app.route('/logout')
def logout():
    session.pop('logged_in', None) # Remove a variável de sessão
    return redirect(url_for('serve_login')) # Redireciona para a página de login

# Rota para servir a página da biblioteca (protegida com login_required)
@app.route('/library')
@login_required # <--- Esta linha PROTEGE a rota
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

    if not book_file.filename.lower().endswith(('.pdf', '.epub', '.mobi', '.txt', '.doc', '.docx')):
        return jsonify({'error': 'Formato de livro não permitido.'}), 400
    if cover_file and not cover_file.filename.lower().endswith(('.jpg', '.jpeg', '.png', '.gif')):
        return jsonify({'error': 'Formato de capa não permitido.'}), 400

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
    if not title or title.strip() == '':
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

# Rota para listar todos os livros
@app.route('/books', methods=['GET'])
@login_required # Protege esta rota
def get_books():
    books = Book.query.order_by(Book.upload_date.desc()).all()
    return jsonify([book.to_dict() for book in books]), 200

# Rota para servir o arquivo de livro para leitura/download
@app.route('/read/<path:filename>', methods=['GET'])
@login_required # Protege esta rota
def read_book(filename):
    if not os.path.abspath(os.path.join(app.config['UPLOAD_FOLDER'], filename)).startswith(os.path.abspath(app.config['UPLOAD_FOLDER'])):
        return "Acesso negado", 403
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# Rota para servir arquivos de capa
@app.route('/covers/<path:filename>', methods=['GET'])
# Não vamos proteger esta rota diretamente, pois a imagem da capa pode ser usada
# pelo `library.html` antes de uma ação de login que verifique o token.
# A verificação de login ocorre quando a página `library` é carregada.
def get_cover(filename):
    if not os.path.abspath(os.path.join(app.config['COVERS_FOLDER'], filename)).startswith(os.path.abspath(app.config['COVERS_FOLDER'])):
        return "Acesso negado", 403
    try:
        return send_from_directory(app.config['COVERS_FOLDER'], filename)
    except Exception:
        return send_from_directory('public', 'placeholder_cover.png')

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

# --- Ponto de Entrada da Aplicação ---
if __name__ == '__main__':
    with app.app_context():
        db.create_all() # Cria as tabelas (se não existirem) antes de iniciar o servidor.
    app.run(debug=True, host='0.0.0.0', port=5173)
