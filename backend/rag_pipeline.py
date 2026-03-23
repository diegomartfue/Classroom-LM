from pypdf import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import OllamaEmbeddings
import chromadb

from ollama_client import chat


def ingest_document(file_path: str):
    try:
        reader = PdfReader(file_path)
        pages = []
        
        for page in reader.pages:
            pages.append(page.extract_text() or "")
            
        text = "".join(pages)

        #chunks
        splitter = RecursiveCharacterTextSplitter(
            chunk_size = 500,
            chunk_overlap = 50,
        )

        chunks = splitter.split_text(text)

        #embeddings
        embeddings = OllamaEmbeddings(model='nomic-embed-text') #embedding model running locally through Ollama
        vectors = embeddings.embed_documents(chunks)

        #store in ChromaDB
        client = chromadb.PersistentClient(path="chroma_db") #saves to disc in a folder called chroma_db
        collection = client.get_or_create_collection(name = "professor_materials") 

        collection.upsert ( #stores chunks
            ids = [str(i) for i in range(len(chunks))],
            documents = chunks,
            embeddings = vectors,
        )
        
        return {"status": "success", "chunks_stored": len(chunks)}
    except Exception as e:
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
            n_results=3
        )
        
        
        #build prompt
        context = "\n\n".join(results["documents"][0])
        
        prompt = f"""You are a classroom AI tutor. A professor has uploaded course materials and a student is asking a question about them.

        Answer the student's question using ONLY the context provided below from the course materials. 
        Be direct and educational. If the answer isn't in the context, say "I don't see that in the uploaded course materials."

        Course Material Context:
        {context}

        Student Question:
        {user_input}

        Answer:"""
        
        answer = chat(prompt)
        return {"status": "success", "answer": answer}
    except Exception as e:
        return {"status": "error", "message": str(e)}