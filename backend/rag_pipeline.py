from pypdf import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import OllamaEmbeddings
import chromadb
import hashlib

from ollama_client import chat


def ingest_document(file_path: str):
    try:
        reader = PdfReader(file_path)
        pages = []
        
        for page in reader.pages:
            pages.append(page.extract_text() or "")
            
        text = "".join(pages)
        text = text.replace("/H9004", "Δ")
        text = text.replace("/H11032", "′")
        text = text.replace("/H11003", "×")
        text = text.replace("/H9001", "α")
        text = text.replace("/H9002", "β")
        text = text.replace("/H9003", "γ")

        #chunks
        splitter = RecursiveCharacterTextSplitter(
            chunk_size = 1000,#was 500
            chunk_overlap = 100, #was 50
        )

        chunks = splitter.split_text(text)

        #embeddings
        embeddings = OllamaEmbeddings(model='nomic-embed-text') #embedding model running locally through Ollama
        vectors = embeddings.embed_documents(chunks)

        #store in ChromaDB
        client = chromadb.PersistentClient(path="chroma_db") #saves to disc in a folder called chroma_db
        collection = client.get_or_create_collection(name = "professor_materials") 

        doc_hash = hashlib.md5(file_path.encode()).hexdigest()[:8] #prevents overloads when multiple files are uploaded
        collection.upsert ( #stores chunks
            ids = [f"{doc_hash}_chunk_{i}" for i in range(len(chunks))],
            documents = chunks,
            embeddings = vectors,
        )
        
        return {"status": "success", "chunks_stored": len(chunks)}
    except Exception as e:
        print(f"INGEST ERROR: {e}")
        return {"status": "error", "message": str(e)}
    
        
def query_rag(user_input: str):
    try:
        client = chromadb.PersistentClient(path="chroma_db")
        collection = client.get_or_create_collection(name="professor_materials")
        
        #embedd the question
        embeddings = OllamaEmbeddings(model='nomic-embed-text')
        vectors = embeddings.embed_query(user_input)
        
        #search chromadb
        results = collection.query(
            query_embeddings=[vectors],
            n_results=4 #was 3
        )
        
        
        #build prompt
        context = "\n\n".join(results["documents"][0])
        
        prompt = f"""You are a classroom AI tutor. Use ONLY the text below to answer. 
        Do not use any outside knowledge. Quote directly from the material when possible.
        If the answer is not in the text below, say "I don't see that in the uploaded course materials."

        COURSE MATERIAL:
        {context}

        STUDENT QUESTION: {user_input}

        ANSWER (based only on the material above):"""
        
        answer = chat(prompt)
        return {"status": "success", "answer": answer}
    except Exception as e:
        return {"status": "error", "message": str(e)}