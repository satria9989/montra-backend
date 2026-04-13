import { initializeApp } from "firebase/app";
import { getFirestore } from "firebase/firestore";
import { getAuth } from "firebase/auth";

const firebaseConfig = {
  apiKey: "AIzaSyAFGvvDz4-riUV58jDJLgxTLc2BsTuUIBA",
  authDomain: "montra-7a1c0.firebaseapp.com",
  projectId: "montra-7a1c0",
  storageBucket: "montra-7a1c0.firebasestorage.app",
  messagingSenderId: "575657994022",
  appId: "1:575657994022:web:9234ea1ecb9f54e29e83e7",
};

const app = initializeApp(firebaseConfig);

export const db = getFirestore(app);
export const auth = getAuth(app);