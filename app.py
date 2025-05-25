import os
from flask import Flask, request, send_from_directory, jsonify, session, redirect, url_for, Response
from flask_sqlalchemy import SQLAlchemy
from uuid import uuid4
from datetime import datetime
from functools import wraps

# Importações do Cloudinary e requests
import cloudinary
import cloudinary.uploader
from cloudinary.utils import cloudinary_url
import requests # Importação adicionada para fazer requisições HTTP

# --- Configuração da Aplicação Flask ---
app = Flask(__name__, static_folder='public')

# Configuração do banco de dados SQLAlchemy
# Usa a variável de ambiente DATABASE_URL fornecida pelo Render para PostgreSQL.
# Se a variável não estiver definida (ex: para desenvolvimento local), usa SQLite.
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL') or 'sqlite:///library.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Limite máximo de tamanho para upload de arquivos (50 MB)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

# CHAVE SECRETA: ESSENCIAL PARA A SEGURANÇA DAS SESSÕES DO FLASK!
# Este valor DEVE ser definido como uma variável de ambiente no Render.
# O segundo argumento de os.environ.get é um valor padrão para desenvolvimento local.
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'uma_chave_secreta_muito_segura_e_aleatoria_para_o_termo_ux_fallback_dev')

# Credenciais de ADMIN para login. EM PRODUÇÃO, SEMPRE USE VARIÁVEIS DE AMBIENTE.
ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')

db = SQLAlchemy(app)

# --- Configuração do Cloudinary ---
# As credenciais são obtidas das variáveis de ambiente definidas no Render.
cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key=os.environ.get('CLOUDINARY_API_KEY'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET')
)

# --- Definição do Modelo do Banco de Dados ---
class Book(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.Text)
    # 'filename' agora armazena o Public ID do arquivo do livro no Cloudinary
    filename = db.Column(db.Text, nullable=False)
    original_filename = db.Column(db.Text, nullable=False)
    # 'cover_filename' agora armazena o Public ID da capa no Cloudinary
    cover_filename = db.Column(db.Text)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        cover_cloud_url = None
        if self.cover_filename:
            # Gera a URL da capa no Cloudinary, com transformações para exibição
            cover_cloud_url, options = cloudinary_url(
                self.cover_filename,
                resource_type="image",
                width=200,    # Largura da imagem da capa
                height=300,   # Altura da imagem da capa
                crop="fill"   # Preenche a área, cortando se necessário
            )
        else:
            # Fallback para uma capa de placeholder se não houver capa
            cover_cloud_url = url_for('static', filename='placeholder_cover.png')

        # Determina a extensão do arquivo original para decidir como servir o livro
        file_extension = self.original_filename.lower().split('.')[-1]
        book_read_url = None

        if file_extension == 'pdf':
            # Para PDFs, usa a rota proxy do Flask para forçar a visualização inline
            book_read_url = url_for('view_pdf', public_id=self.filename)
        else:
            # Para outros formatos (EPUB, DOCX, TXT), usa a URL direta do Cloudinary.
            # Estes formatos geralmente resultam em download, pois navegadores não os exibem nativamente.
            book_cloud_url, options = cloudinary_url(self.filename, resource_type="raw")
            book_read_url = book_cloud_url

        return {
            'id': self.id,
            'title': self.title,
            'filename': self.filename, # Mantém o public_id para operações futuras
            'original_filename': self.original_filename,
            'cover_url': cover_cloud_url, # URL da capa para o frontend
            'read_url': book_read_url # URL para o frontend (proxy Flask para PDF, Cloudinary direto para outros)
        }

# Garante que as tabelas do banco de dados são criadas quando o aplicativo inicia.
# Isso é executado ao carregar o módulo, o que o Gunicorn fará.
# Em um ambiente de produção com PostgreSQL, as tabelas serão criadas na primeira vez.
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
        book_title = request.form.get('title', original_filename.split('.')[0])

        book_public_id = None
        try:
            upload_result = cloudinary.uploader.upload(
                book_file,
                resource_type="raw",
                folder="library_books",
                public_id=f"{book_title.replace(' ', '_').lower()}_{uuid4()}"
            )
            book_public_id = upload_result['public_id']
        except Exception as e:
            print(f"Erro ao enviar o livro para o Cloudinary: {str(e)}")
            return jsonify({'error': f'Erro ao enviar o livro para o Cloudinary: {str(e)}'}), 500

        cover_public_id = None
        cover_file = request.files.get('cover_file')
        if cover_file and cover_file.filename != '':
            try:
                cover_upload_result = cloudinary.uploader.upload(
                    cover_file,
                    folder="library_covers",
                    public_id=f"cover_{book_public_id}"
                )
                cover_public_id = cover_upload_result['public_id']
            except Exception as e:
                print(f"Aviso: Erro ao enviar a capa para o Cloudinary: {str(e)}")

        new_book = Book(
            title=book_title,
            filename=book_public_id,
            original_filename=original_filename,
            cover_filename=cover_public_id
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

# NOVA ROTA: Proxy para visualização de PDFs inline
@app.route('/view_pdf/<public_id>')
@login_required
def view_pdf(public_id):
    try:
        # Gera a URL direta do Cloudinary para o arquivo PDF raw
        pdf_url, _ = cloudinary_url(public_id, resource_type="raw")

        # Busca o conteúdo do PDF do Cloudinary
        response = requests.get(pdf_url, stream=True)
        response.raise_for_status() # Levanta uma exceção para códigos de status HTTP ruins

        # Obtém o nome original do arquivo do banco de dados para o cabeçalho Content-Disposition
        book = Book.query.filter_by(filename=public_id).first()
        if not book:
            return "Livro não encontrado.", 404
        
        original_filename = book.original_filename
        
        # Define os cabeçalhos para forçar a visualização inline do PDF no navegador
        headers = {
            'Content-Type': 'application/pdf',
            'Content-Disposition': f'inline; filename="{original_filename}"'
        }

        # Retorna o conteúdo do PDF como uma resposta Flask, em chunks
        return Response(response.iter_content(chunk_size=8192), headers=headers)

    except requests.exceptions.RequestException as e:
        print(f"Erro ao buscar PDF do Cloudinary: {e}")
        return "Erro ao carregar o PDF.", 500
    except Exception as e:
        print(f"Erro inesperado ao visualizar PDF: {e}")
        return "Erro interno do servidor.", 500

@app.route('/delete-book/<int:book_id>', methods=['DELETE'])
@login_required
def delete_book(book_id):
    book_to_delete = Book.query.get(book_id)
    if not book_to_delete:
        return jsonify({'message': 'Livro não encontrado no banco de dados.'}), 404

    try:
        # Deleta o arquivo do livro do Cloudinary usando o Public ID
        if book_to_delete.filename:
            cloudinary.uploader.destroy(book_to_delete.filename, resource_type="raw")

        # Deleta a capa do Cloudinary usando o Public ID
        if book_to_delete.cover_filename:
            cloudinary.uploader.destroy(book_to_delete.cover_filename, resource_type="image")

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
