from fastapi import FastAPI, HTTPException, Depends
from typing import List
import uuid
import sqlite3
from models import Produto, Usuario, Fornecedor, init_db, get_db

app = FastAPI()
init_db()

@app.post("/usuarios/", response_model=Usuario)
def cadastrar_usuario(usuario: Usuario, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    usuario.uuid = str(uuid.uuid4())
    
    cursor.execute(
        "INSERT INTO usuarios VALUES (?, ?, ?, ?, ?, ?)",
        (usuario.uuid, usuario.cnpj, usuario.nome, usuario.email, usuario.senha, usuario.tipo.value)
    )
    db.commit()
    return usuario

@app.post("/produtos/", response_model=Produto)
def cadastrar_produto(produto: Produto, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    produto.uuid = str(uuid.uuid4())
    
    cursor.execute(
        "INSERT INTO produtos VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (produto.uuid, produto.nome, produto.descricao, produto.categoria, produto.quantidade, produto.preco_unitario, produto.data_validade, produto.lote, produto.fornecedor_uuid, produto.localizacao, produto.status.value)
    )
    db.commit()
    return produto

@app.post("/fornecedores/", response_model=Fornecedor)
def cadastrar_fornecedor(fornecedor: Fornecedor, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    fornecedor.uuid = str(uuid.uuid4())
    
    cursor.execute(
        "INSERT INTO fornecedores VALUES (?, ?, ?, ?)",
        (fornecedor.uuid, fornecedor.nome, fornecedor.telefone, fornecedor.email)
    )
    db.commit()
    return fornecedor

@app.get("/produtos/", response_model=List[Produto])
def listar_produtos(db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM produtos")
    return [Produto(**dict(row)) for row in cursor.fetchall()]

@app.get("/produtos/{nome}", response_model=Produto)
def obter_produto(nome: str, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM produtos WHERE nome = ?", (nome,))
    produto = cursor.fetchone()
    if not produto:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    return Produto(**dict(produto))


@app.delete("/produtos/{uuid}", response_model=dict)
def deletar_produto(uuid: str, db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    
    cursor.execute("SELECT * FROM produtos WHERE uuid = ?", (uuid,))
    produto = cursor.fetchone()
    
    if produto is None:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    
    cursor.execute("DELETE FROM produtos WHERE uuid = ?", (uuid,))
    db.commit()
    
    return {"message": "Produto deletado com sucesso"}

@app.get("/fornecedores/", response_model=List[Fornecedor])
def listar_fornecedores(db: sqlite3.Connection = Depends(get_db)):
    cursor = db.cursor()
    cursor.execute("SELECT * FROM fornecedores")
    return [Fornecedor(**dict(row)) for row in cursor.fetchall()]
