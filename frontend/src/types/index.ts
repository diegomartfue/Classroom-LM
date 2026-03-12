/**
 * ============================================================================
 * TYPES DEFINITIONS - LearnAI Platform
 * ============================================================================
 * 
 * This file contains all TypeScript interfaces and types used throughout
 * the application. Organized by domain for easy navigation.
 * 
 * To add new types:
 * 1. Identify the domain (User, Course, AI, etc.)
 * 2. Add to the appropriate section
 * 3. Export at the bottom
 * 
 * ============================================================================
 */

// =============================================================================
// USER & AUTHENTICATION TYPES
// =============================================================================

export type UserRole = 'professor' | 'student';

export interface User {
  id: string;
  email: string;
  name: string;
  role: UserRole;
  avatar?: string;
  createdAt: Date;
  lastLoginAt: Date;
}

export interface Professor extends User {
  role: 'professor';
  department: string;
  title: string; // e.g., "Dr.", "Prof.", "Associate Prof."
  courses: string[]; // Course IDs
}

export interface Student extends User {
  role: 'student';
  studentId: string;
  major: string;
  enrollmentYear: number;
  enrolledCourses: string[]; // Course IDs
  overallProgress: number; // 0-100
  streakDays: number;
}

// =============================================================================
// COURSE TYPES
// =============================================================================

export type CourseStatus = 'active' | 'draft' | 'archived';

export interface Course {
  id: string;
  code: string; // e.g., "MECH-101"
  name: string;
  description: string;
  professorId: string;
  status: CourseStatus;
  createdAt: Date;
  updatedAt: Date;
  studentIds: string[];
  moduleIds: string[];
  coverImage?: string;
  syllabus?: string;
}

export interface CourseModule {
  id: string;
  courseId: string;
  title: string;
  description: string;
  content: string; // HTML/Rich text content
  order: number;
  estimatedDuration: number; // in minutes
  isAIGenerated: boolean;
  aiMetadata?: AIModuleMetadata;
  createdAt: Date;
  updatedAt: Date;
}

export interface AIModuleMetadata {
  generatedFor: 'class' | 'student';
  targetStudentId?: string;
  difficultyLevel: number; // 1-5
  learningObjectives: string[];
  personalizationReason?: string;
}

// =============================================================================
// QUIZ & ASSESSMENT TYPES
// =============================================================================

export type QuestionType = 'multiple_choice' | 'fill_blank' | 'equation_solving' | 'diagram_analysis' | 'essay';

export interface Quiz {
  id: string;
  courseId: string;
  title: string;
  description: string;
  questions: Question[];
  timeLimit?: number; // in minutes, undefined = no limit
  totalPoints: number;
  isAIGenerated: boolean;
  aiMetadata?: AIQuizMetadata;
  createdAt: Date;
  dueDate?: Date;
  status: 'draft' | 'published' | 'closed';
}

export interface AIQuizMetadata {
  generatedFor: 'class' | 'student';
  targetStudentId?: string;
  difficultyDistribution: {
    easy: number;
    medium: number;
    hard: number;
  };
  topicFocus: string[];
}

export interface Question {
  id: string;
  type: QuestionType;
  question: string;
  points: number;
  // For multiple choice
  options?: string[];
  correctOptionIndex?: number;
  // For fill blank and equation
  correctAnswer?: string;
  // For diagram analysis
  diagramUrl?: string;
  diagramDescription?: string;
  // For essay
  rubric?: string;
  // AI-generated explanation
  explanation?: string;
}

export interface QuizAttempt {
  id: string;
  quizId: string;
  studentId: string;
  startedAt: Date;
  submittedAt?: Date;
  answers: StudentAnswer[];
  score?: number;
  maxScore: number;
  status: 'in_progress' | 'submitted' | 'graded';
  aiFeedback?: AIFeedback;
}

export interface StudentAnswer {
  questionId: string;
  answer: string | number; // String for text, number for option index
  isCorrect?: boolean;
  pointsEarned?: number;
  aiFeedback?: string;
}

export interface AIFeedback {
  overallFeedback: string;
  strengths: string[];
  weaknesses: string[];
  suggestedTopics: string[];
  personalizedRecommendations: string;
}

// =============================================================================
// AI TUTOR TYPES
// =============================================================================

export type MessageType = 'text' | 'equation' | 'diagram' | 'code';

export interface ChatMessage {
  id: string;
  conversationId: string;
  sender: 'user' | 'ai';
  type: MessageType;
  content: string;
  timestamp: Date;
  // For equations
  latexContent?: string;
  // For diagrams
  imageUrl?: string;
  // Metadata
  referencedCourseId?: string;
  referencedModuleId?: string;
}

export interface Conversation {
  id: string;
  userId: string;
  title: string;
  messages: ChatMessage[];
  createdAt: Date;
  updatedAt: Date;
  contextCourseId?: string;
}

export interface AITutorRequest {
  message: string;
  conversationId?: string;
  contextCourseId?: string;
  contextModuleId?: string;
  includeEquationSupport: boolean;
  includeDiagramAnalysis: boolean;
}

// =============================================================================
// STUDENT PROGRESS TYPES
// =============================================================================

export interface StudentProgress {
  studentId: string;
  courseId: string;
  overallMastery: number; // 0-100
  topicMastery: TopicMastery[];
  quizScores: QuizScoreRecord[];
  studyTimeMinutes: number;
  lastActivityAt: Date;
  streakDays: number;
}

export interface TopicMastery {
  topic: string;
  masteryLevel: number; // 0-100
  attempts: number;
  lastAssessedAt: Date;
}

export interface QuizScoreRecord {
  quizId: string;
  quizTitle: string;
  score: number;
  maxScore: number;
  completedAt: Date;
}

// =============================================================================
// AI CONTENT GENERATION TYPES
// =============================================================================

export interface ContentGenerationRequest {
  type: 'module' | 'quiz';
  courseId: string;
  targetType: 'general' | 'personalized';
  targetStudentId?: string;
  parameters: ModuleGenerationParams | QuizGenerationParams;
}

export interface ModuleGenerationParams {
  topic: string;
  difficultyLevel: number; // 1-5
  learningObjectives: string[];
  estimatedDuration: number;
  includeEquations: boolean;
  includeDiagrams: boolean;
}

export interface QuizGenerationParams {
  title: string;
  questionCount: number;
  questionTypes: QuestionType[];
  difficultyDistribution: {
    easy: number;
    medium: number;
    hard: number;
  };
  topicFocus: string[];
  timeLimit?: number;
}

// =============================================================================
// NOTIFICATION TYPES
// =============================================================================

export type NotificationType = 'assignment' | 'grade' | 'announcement' | 'ai_suggestion' | 'deadline';

export interface Notification {
  id: string;
  userId: string;
  type: NotificationType;
  title: string;
  message: string;
  isRead: boolean;
  createdAt: Date;
  actionUrl?: string;
}

// =============================================================================
// UI/STATE TYPES
// =============================================================================

export type ViewMode = 'list' | 'grid';

export interface FilterState {
  search: string;
  status: string | null;
  sortBy: 'date' | 'name' | 'progress';
  sortOrder: 'asc' | 'desc';
}

export interface LoadingState {
  isLoading: boolean;
  error: string | null;
}

// =============================================================================
// MOCK DATA TYPE (for development)
// =============================================================================

export interface MockDatabase {
  users: User[];
  professors: Professor[];
  students: Student[];
  courses: Course[];
  modules: CourseModule[];
  quizzes: Quiz[];
  quizAttempts: QuizAttempt[];
  conversations: Conversation[];
  progressRecords: StudentProgress[];
  notifications: Notification[];
}
