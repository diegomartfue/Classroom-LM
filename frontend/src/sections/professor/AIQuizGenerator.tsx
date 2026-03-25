/**
 * ============================================================================
 * AI QUIZ GENERATOR - LearnAI Platform
 * ============================================================================
 * 
 * This component allows professors to generate AI-powered quizzes.
 * Supports multiple question types including equations and diagram analysis.
 * 
 * FEATURES:
 * - Multiple question types (MC, fill blank, equations, diagrams)
 * - Difficulty distribution control
 * - General or personalized quiz generation
 * - Question preview and editing
 * - Drag-to-reorder questions
 * 
 * ============================================================================
 */

import { useState } from 'react';
import { cn } from '@/lib/utils';
import { useApp } from '@/contexts';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';

import { Badge } from '@/components/ui/badge';
import { Slider } from '@/components/ui/slider';
import { Checkbox } from '@/components/ui/checkbox';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Sparkles,
  ArrowLeft,
  Loader2,
  FileQuestion,
  User,
  Users,
  Clock,
  CheckSquare,
  Edit2,
  GripVertical,
  Trash2,
  Plus,
  FunctionSquare,
  Image as ImageIcon,
  AlignLeft,
  List,
  Eye,
  Send,
} from 'lucide-react';
import type { QuizGenerationParams, QuestionType, Question } from '@/types';
import { mockStudents } from '@/data/mockData';

// =============================================================================
// QUESTION TYPE CONFIG
// =============================================================================

const QUESTION_TYPES: { type: QuestionType; label: string; icon: React.ElementType; description: string }[] = [
  { type: 'multiple_choice', label: 'Multiple Choice', icon: List, description: 'Select one correct answer' },
  { type: 'fill_blank', label: 'Fill in Blank', icon: AlignLeft, description: 'Short text answer' },
  { type: 'equation_solving', label: 'Equation Solving', icon: FunctionSquare, description: 'Mathematical problems' },
  { type: 'diagram_analysis', label: 'Diagram Analysis', icon: ImageIcon, description: 'Analyze images/diagrams' },
];

// =============================================================================
// QUESTION CARD COMPONENT
// =============================================================================

interface QuestionCardProps {
  question: Question;
  index: number;
  onEdit: () => void;
  onDelete: () => void;
}

function QuestionCard({ question, index, onEdit, onDelete }: QuestionCardProps) {
  const typeConfig = QUESTION_TYPES.find(t => t.type === question.type);
  const Icon = typeConfig?.icon || FileQuestion;

  return (
    <div className="bg-white rounded-xl border shadow-sm p-4 group hover:shadow-md transition-shadow">
      <div className="flex items-start gap-3">
        <div className="flex flex-col items-center gap-1">
          <div className="w-8 h-8 bg-indigo-100 rounded-lg flex items-center justify-center text-indigo-600 font-semibold text-sm">
            {index + 1}
          </div>
          <GripVertical className="w-5 h-5 text-slate-300 cursor-grab" />
        </div>
        
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-2">
            <Badge variant="secondary" className="text-xs gap-1">
              <Icon className="w-3 h-3" />
              {typeConfig?.label}
            </Badge>
            <Badge variant="outline" className="text-xs">
              {question.points} pts
            </Badge>
          </div>
          
          <p className="text-sm text-slate-700 mb-2">{question.question}</p>
          
          {question.type === 'multiple_choice' && question.options && (
            <div className="space-y-1 ml-4">
              {question.options.map((opt, i) => (
                <div
                  key={i}
                  className={cn(
                    'text-sm flex items-center gap-2',
                    i === question.correctOptionIndex ? 'text-green-600 font-medium' : 'text-slate-500'
                  )}
                >
                  <div
                    className={cn(
                      'w-4 h-4 rounded-full border-2 flex items-center justify-center',
                      i === question.correctOptionIndex
                        ? 'border-green-500 bg-green-500'
                        : 'border-slate-300'
                    )}
                  >
                    {i === question.correctOptionIndex && <CheckSquare className="w-3 h-3 text-white" />}
                  </div>
                  {opt}
                </div>
              ))}
            </div>
          )}
          
          {(question.type === 'fill_blank' || question.type === 'equation_solving') && question.correctAnswer && (
            <p className="text-sm text-green-600">
              Answer: <span className="font-medium">{question.correctAnswer}</span>
            </p>
          )}
        </div>
        
        <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={onEdit}>
            <Edit2 className="w-4 h-4" />
          </Button>
          <Button variant="ghost" size="icon" className="h-8 w-8 text-red-500" onClick={onDelete}>
            <Trash2 className="w-4 h-4" />
          </Button>
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

interface AIQuizGeneratorProps {
  onViewChange: (view: string) => void;
}

export function AIQuizGenerator({ onViewChange }: AIQuizGeneratorProps) {
  const { courses, generateAIQuiz, isGenerating } = useApp();
  
  // Form state
  const [selectedCourse, setSelectedCourse] = useState<string>('');
  const [quizTitle, setQuizTitle] = useState('');
  const [targetType, setTargetType] = useState<'general' | 'personalized'>('general');
  const [targetStudent, setTargetStudent] = useState<string>('');
  const [questionCount, setQuestionCount] = useState(10);
  const [selectedTypes, setSelectedTypes] = useState<QuestionType[]>(['multiple_choice', 'equation_solving']);
  const [difficultyDistribution, setDifficultyDistribution] = useState({ easy: 30, medium: 50, hard: 20 });
  const [topicFocus, setTopicFocus] = useState('');
  const [timeLimit, setTimeLimit] = useState(30);
  
  // Generated quiz state
  const [generatedQuiz, setGeneratedQuiz] = useState<any>(null);
  const [activeTab, setActiveTab] = useState('configure');

  const toggleQuestionType = (type: QuestionType) => {
    setSelectedTypes(prev =>
      prev.includes(type)
        ? prev.filter(t => t !== type)
        : [...prev, type]
    );
  };

  const handleGenerate = async () => {
    if (!selectedCourse || !quizTitle || selectedTypes.length === 0) return;

    const params: QuizGenerationParams = {
      title: quizTitle,
      questionCount,
      questionTypes: selectedTypes,
      difficultyDistribution,
      topicFocus: topicFocus.split(',').map(t => t.trim()).filter(Boolean),
      timeLimit,
    };

    const quiz = await generateAIQuiz(
      selectedCourse,
      params,
      targetType === 'personalized' ? targetStudent : undefined
    );

    setGeneratedQuiz(quiz);
    setActiveTab('preview');
  };

  const handlePublish = () => {
    // Publish the quiz
    onViewChange('courses');
  };

  const selectedCourseData = courses.find(c => c.id === selectedCourse);
  const enrolledStudents = selectedCourseData
    ? mockStudents.filter(s => selectedCourseData.studentIds.includes(s.id))
    : [];

  return (
    <div className="h-full flex flex-col animate-in fade-in duration-500">
      {/* Header */}
      <div className="flex items-center justify-between p-6 border-b bg-white">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" onClick={() => onViewChange('dashboard')}>
            <ArrowLeft className="w-5 h-5" />
          </Button>
          <div>
            <h1 className="text-2xl font-bold text-slate-800 flex items-center gap-2">
              <Sparkles className="w-6 h-6 text-teal-500" />
              AI Quiz Creator
            </h1>
            <p className="text-slate-500">Generate adaptive assessments with AI</p>
          </div>
        </div>
        
        {generatedQuiz && (
          <div className="flex gap-2">
            <Button variant="outline" className="gap-2" onClick={() => setActiveTab('configure')}>
              <Edit2 className="w-4 h-4" />
              Regenerate
            </Button>
            <Button variant="outline" className="gap-2">
              <Eye className="w-4 h-4" />
              Preview
            </Button>
            <Button className="gap-2 bg-teal-600 hover:bg-teal-700" onClick={handlePublish}>
              <Send className="w-4 h-4" />
              Publish Quiz
            </Button>
          </div>
        )}
      </div>

      {/* Main Content */}
      <div className="flex-1 flex overflow-hidden">
        <Tabs value={activeTab} onValueChange={setActiveTab} className="flex-1 flex">
          {/* Left Panel - Configuration */}
          <div className="w-96 border-r bg-slate-50 flex flex-col">
            <TabsList className="w-full rounded-none border-b bg-white p-0">
              <TabsTrigger value="configure" className="flex-1 rounded-none data-[state=active]:bg-slate-50">
                Configure
              </TabsTrigger>
              <TabsTrigger
                value="preview"
                className="flex-1 rounded-none data-[state=active]:bg-slate-50"
                disabled={!generatedQuiz}
              >
                Preview
              </TabsTrigger>
            </TabsList>

            <ScrollArea className="flex-1">
              <TabsContent value="configure" className="m-0 p-6 space-y-6">
                {/* Quiz Title */}
                <div className="space-y-2">
                  <Label>Quiz Title</Label>
                  <Input
                    value={quizTitle}
                    onChange={(e) => setQuizTitle(e.target.value)}
                    placeholder="e.g., Thermodynamics Midterm"
                  />
                </div>

                {/* Course Selection */}
                <div className="space-y-2">
                  <Label>Course</Label>
                  <Select value={selectedCourse} onValueChange={setSelectedCourse}>
                    <SelectTrigger>
                      <SelectValue placeholder="Select a course" />
                    </SelectTrigger>
                    <SelectContent>
                      {courses.map(course => (
                        <SelectItem key={course.id} value={course.id}>
                          {course.code} - {course.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                {/* Target Type */}
                <div className="space-y-2">
                  <Label>Target Audience</Label>
                  <div className="grid grid-cols-2 gap-2">
                    <button
                      onClick={() => setTargetType('general')}
                      className={cn(
                        'p-3 rounded-xl border-2 text-left transition-all',
                        targetType === 'general'
                          ? 'border-indigo-500 bg-indigo-50'
                          : 'border-slate-200 hover:border-indigo-200'
                      )}
                    >
                      <Users className="w-4 h-4 mb-1 text-indigo-500" />
                      <p className="font-medium text-xs">Entire Class</p>
                    </button>
                    <button
                      onClick={() => setTargetType('personalized')}
                      className={cn(
                        'p-3 rounded-xl border-2 text-left transition-all',
                        targetType === 'personalized'
                          ? 'border-teal-500 bg-teal-50'
                          : 'border-slate-200 hover:border-teal-200'
                      )}
                    >
                      <User className="w-4 h-4 mb-1 text-teal-500" />
                      <p className="font-medium text-xs">Personalized</p>
                    </button>
                  </div>
                </div>

                {/* Student Selection */}
                {targetType === 'personalized' && (
                  <div className="space-y-2 animate-in slide-in-from-top-2">
                    <Label>Target Student</Label>
                    <Select value={targetStudent} onValueChange={setTargetStudent}>
                      <SelectTrigger>
                        <SelectValue placeholder="Select a student" />
                      </SelectTrigger>
                      <SelectContent>
                        {enrolledStudents.map(student => (
                          <SelectItem key={student.id} value={student.id}>
                            {student.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                )}

                {/* Question Count */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <Label>Number of Questions</Label>
                    <span className="text-sm font-medium">{questionCount}</span>
                  </div>
                  <Slider
                    value={[questionCount]}
                    onValueChange={(v) => setQuestionCount(v[0])}
                    min={5}
                    max={50}
                    step={1}
                  />
                </div>

                {/* Question Types */}
                <div className="space-y-3">
                  <Label>Question Types</Label>
                  <div className="space-y-2">
                    {QUESTION_TYPES.map((type) => (
                      <div
                        key={type.type}
                        className={cn(
                          'flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-all',
                          selectedTypes.includes(type.type)
                            ? 'border-indigo-500 bg-indigo-50'
                            : 'border-slate-200 hover:border-indigo-200'
                        )}
                        onClick={() => toggleQuestionType(type.type)}
                      >
                        <Checkbox
                          checked={selectedTypes.includes(type.type)}
                          onCheckedChange={() => {}}
                        />
                        <type.icon className={cn(
                          'w-4 h-4',
                          selectedTypes.includes(type.type) ? 'text-indigo-500' : 'text-slate-400'
                        )} />
                        <div className="flex-1">
                          <p className={cn(
                            'text-sm font-medium',
                            selectedTypes.includes(type.type) ? 'text-indigo-700' : 'text-slate-700'
                          )}>
                            {type.label}
                          </p>
                          <p className="text-xs text-slate-500">{type.description}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Difficulty Distribution */}
                <div className="space-y-3">
                  <Label>Difficulty Distribution</Label>
                  <div className="space-y-3">
                    <div>
                      <div className="flex justify-between text-sm mb-1">
                        <span className="text-green-600">Easy</span>
                        <span>{difficultyDistribution.easy}%</span>
                      </div>
                      <Slider
                        value={[difficultyDistribution.easy]}
                        onValueChange={(v) => setDifficultyDistribution(prev => ({ ...prev, easy: v[0] }))}
                        min={0}
                        max={100}
                      />
                    </div>
                    <div>
                      <div className="flex justify-between text-sm mb-1">
                        <span className="text-yellow-600">Medium</span>
                        <span>{difficultyDistribution.medium}%</span>
                      </div>
                      <Slider
                        value={[difficultyDistribution.medium]}
                        onValueChange={(v) => setDifficultyDistribution(prev => ({ ...prev, medium: v[0] }))}
                        min={0}
                        max={100}
                      />
                    </div>
                    <div>
                      <div className="flex justify-between text-sm mb-1">
                        <span className="text-red-600">Hard</span>
                        <span>{difficultyDistribution.hard}%</span>
                      </div>
                      <Slider
                        value={[difficultyDistribution.hard]}
                        onValueChange={(v) => setDifficultyDistribution(prev => ({ ...prev, hard: v[0] }))}
                        min={0}
                        max={100}
                      />
                    </div>
                  </div>
                </div>

                {/* Topic Focus */}
                <div className="space-y-2">
                  <Label>Topic Focus (optional)</Label>
                  <Textarea
                    value={topicFocus}
                    onChange={(e) => setTopicFocus(e.target.value)}
                    placeholder="Enter topics to focus on, separated by commas..."
                    rows={3}
                  />
                </div>

                {/* Time Limit */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <Label className="flex items-center gap-2">
                      <Clock className="w-4 h-4" />
                      Time Limit (minutes)
                    </Label>
                    <span className="text-sm font-medium">{timeLimit} min</span>
                  </div>
                  <Slider
                    value={[timeLimit]}
                    onValueChange={(v) => setTimeLimit(v[0])}
                    min={10}
                    max={180}
                    step={5}
                  />
                </div>

                {/* Generate Button */}
                <Button
                  className="w-full gap-2 bg-teal-600 hover:bg-teal-700 h-12"
                  onClick={handleGenerate}
                  disabled={isGenerating || !selectedCourse || !quizTitle || selectedTypes.length === 0}
                >
                  {isGenerating ? (
                    <>
                      <Loader2 className="w-5 h-5 animate-spin" />
                      Generating Quiz...
                    </>
                  ) : (
                    <>
                      <Sparkles className="w-5 h-5" />
                      Generate Quiz
                    </>
                  )}
                </Button>
              </TabsContent>

              <TabsContent value="preview" className="m-0 p-6">
                {generatedQuiz && (
                  <div className="space-y-4">
                    <div className="p-4 bg-teal-50 rounded-xl border border-teal-200">
                      <p className="font-medium text-teal-800">Quiz Generated!</p>
                      <p className="text-sm text-teal-700">
                        {generatedQuiz.questions.length} questions • {generatedQuiz.totalPoints} points
                      </p>
                    </div>
                    
                    <div className="space-y-2">
                      <Label>Quiz Title</Label>
                      <Input value={generatedQuiz.title} readOnly />
                    </div>
                    
                    <div className="flex flex-wrap gap-2">
                      <Badge variant="secondary">{generatedQuiz.questions.length} Questions</Badge>
                      <Badge variant="secondary">{generatedQuiz.totalPoints} Points</Badge>
                      <Badge variant="secondary">{generatedQuiz.timeLimit} min</Badge>
                    </div>
                  </div>
                )}
              </TabsContent>
            </ScrollArea>
          </div>

          {/* Right Panel - Question Preview */}
          <div className="flex-1 bg-slate-100 p-6 overflow-auto">
            {activeTab === 'preview' && generatedQuiz ? (
              <div className="max-w-3xl mx-auto space-y-4">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-semibold">Questions ({generatedQuiz.questions.length})</h2>
                  <Button variant="outline" size="sm" className="gap-1">
                    <Plus className="w-4 h-4" />
                    Add Question
                  </Button>
                </div>
                
                <div className="space-y-3">
                  {generatedQuiz.questions.map((question: Question, index: number) => (
                    <QuestionCard
                      key={question.id}
                      question={question}
                      index={index}
                      onEdit={() => {}}
                      onDelete={() => {}}
                    />
                  ))}
                </div>
              </div>
            ) : (
              <div className="h-full flex items-center justify-center">
                <div className="text-center space-y-4">
                  <div className="w-24 h-24 bg-teal-100 rounded-full flex items-center justify-center mx-auto">
                    <FileQuestion className="w-12 h-12 text-teal-400" />
                  </div>
                  <div>
                    <h3 className="text-xl font-semibold text-slate-700">Create an AI Quiz</h3>
                    <p className="text-slate-500 max-w-md mt-2">
                      Configure your quiz settings and let AI generate questions tailored to your students' needs.
                    </p>
                  </div>
                </div>
              </div>
            )}
          </div>
        </Tabs>
      </div>
    </div>
  );
}
