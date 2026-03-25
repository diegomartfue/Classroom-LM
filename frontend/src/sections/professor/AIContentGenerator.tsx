/**
 * ============================================================================
 * AI CONTENT GENERATOR - LearnAI Platform
 * ============================================================================
 * 
 * This component allows professors to generate AI-powered learning modules.
 * Supports both general class modules and personalized content for specific students.
 * 
 * FEATURES:
 * - Configure generation parameters
 * - Generate general or personalized content
 * - Rich text editor for reviewing/editing
 * - Preview before publishing
 * - Equation and diagram support
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
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Slider } from '@/components/ui/slider';
import { Switch } from '@/components/ui/switch';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Separator } from '@/components/ui/separator';
import {
  Sparkles,
  ArrowLeft,
  Loader2,
  User,
  Users,
  Clock,
  Target,
  Edit3,
  Save,
  Eye,
  CheckCircle,
  FunctionSquare,
  Image as ImageIcon,
  Plus,
} from 'lucide-react';
import type { ModuleGenerationParams } from '@/types';
import { mockStudents } from '@/data/mockData';

// =============================================================================
// RICH TEXT EDITOR (Simplified)
// =============================================================================

interface RichTextEditorProps {
  content: string;
  onChange: (content: string) => void;
}

function RichTextEditor({ content, onChange }: RichTextEditorProps) {
  const [showEquationModal, setShowEquationModal] = useState(false);
  const [equationInput, setEquationInput] = useState('');

  const insertEquation = () => {
    if (equationInput.trim()) {
      const newContent = content + `\n<p class="equation">[Equation: ${equationInput}]</p>\n`;
      onChange(newContent);
      setEquationInput('');
      setShowEquationModal(false);
    }
  };

  return (
    <div className="relative border rounded-xl overflow-hidden bg-white">
      {/* Toolbar */}
      <div className="flex items-center gap-1 p-2 border-b bg-slate-50">
        <Button variant="ghost" size="sm" className="h-8 px-2 font-bold">B</Button>
        <Button variant="ghost" size="sm" className="h-8 px-2 italic">I</Button>
        <Separator orientation="vertical" className="h-6 mx-1" />
        <Button variant="ghost" size="sm" className="h-8 px-2">
          <Plus className="w-4 h-4" />
        </Button>
        <Button variant="ghost" size="sm" className="h-8 px-2">
          1.
        </Button>
        <Separator orientation="vertical" className="h-6 mx-1" />
        <Button
          variant="ghost"
          size="sm"
          className="h-8 px-2 gap-1 text-indigo-600"
          onClick={() => setShowEquationModal(true)}
        >
          <FunctionSquare className="w-4 h-4" />
          Equation
        </Button>
        <Button variant="ghost" size="sm" className="h-8 px-2 gap-1 text-teal-600">
          <ImageIcon className="w-4 h-4" />
          Diagram
        </Button>
      </div>

      {/* Editor Area */}
      <Textarea
        value={content}
        onChange={(e) => onChange(e.target.value)}
        className="min-h-[400px] border-0 rounded-none resize-none focus-visible:ring-0 font-mono text-sm"
        placeholder="AI-generated content will appear here..."
      />

      {/* Equation Modal */}
      {showEquationModal && (
        <div className="absolute inset-0 bg-black/50 flex items-center justify-center z-50">
          <Card className="w-96">
            <CardHeader>
              <CardTitle className="text-lg">Insert Equation</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <Label>LaTeX Expression</Label>
                <Input
                  value={equationInput}
                  onChange={(e) => setEquationInput(e.target.value)}
                  placeholder="e.g., F = ma"
                  className="font-mono"
                />
              </div>
              <div className="flex gap-2 justify-end">
                <Button variant="outline" onClick={() => setShowEquationModal(false)}>
                  Cancel
                </Button>
                <Button onClick={insertEquation}>Insert</Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}

// =============================================================================
// MAIN COMPONENT
// =============================================================================

interface AIContentGeneratorProps {
  onViewChange: (view: string) => void;
}

export function AIContentGenerator({ onViewChange }: AIContentGeneratorProps) {
  const { generateAIModule, isGenerating, courses } = useApp();
  
  // Form state
  const [selectedCourse, setSelectedCourse] = useState<string>('');
  const [targetType, setTargetType] = useState<'general' | 'personalized'>('general');
  const [targetStudent, setTargetStudent] = useState<string>('');
  const [topic, setTopic] = useState('');
  const [difficultyLevel, setDifficultyLevel] = useState([3]);
  const [estimatedDuration, setEstimatedDuration] = useState(45);
  const [learningObjectives, setLearningObjectives] = useState('');
  const [includeEquations, setIncludeEquations] = useState(true);
  const [includeDiagrams, setIncludeDiagrams] = useState(false);
  
  // Generated content state
  const [generatedModule, setGeneratedModule] = useState<any>(null);
  const [editedContent, setEditedContent] = useState('');
  const [activeTab, setActiveTab] = useState('configure');

  const handleGenerate = async () => {
    if (!selectedCourse || !topic) return;

    const params: ModuleGenerationParams = {
      topic,
      difficultyLevel: difficultyLevel[0],
      learningObjectives: learningObjectives.split('\n').filter(Boolean),
      estimatedDuration,
      includeEquations,
      includeDiagrams,
    };

    const module = await generateAIModule(
      selectedCourse,
      params,
      targetType === 'personalized' ? targetStudent : undefined
    );

    setGeneratedModule(module);
    setEditedContent(module.content);
    setActiveTab('edit');
  };

  const handleSave = () => {
    // Save the edited module
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
              <Sparkles className="w-6 h-6 text-indigo-500" />
              AI Learning Module Generator
            </h1>
            <p className="text-slate-500">Create personalized or class-wide learning content</p>
          </div>
        </div>
        
        {generatedModule && (
          <div className="flex gap-2">
            <Button variant="outline" className="gap-2">
              <Eye className="w-4 h-4" />
              Preview
            </Button>
            <Button className="gap-2 bg-indigo-600 hover:bg-indigo-700" onClick={handleSave}>
              <Save className="w-4 h-4" />
              Save Module
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
                value="edit" 
                className="flex-1 rounded-none data-[state=active]:bg-slate-50"
                disabled={!generatedModule}
              >
                Edit
              </TabsTrigger>
            </TabsList>

            <TabsContent value="configure" className="flex-1 m-0 p-6 space-y-6 overflow-auto">
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
                      'p-4 rounded-xl border-2 text-left transition-all',
                      targetType === 'general'
                        ? 'border-indigo-500 bg-indigo-50'
                        : 'border-slate-200 hover:border-indigo-200'
                    )}
                  >
                    <Users className="w-5 h-5 mb-2 text-indigo-500" />
                    <p className="font-medium text-sm">Entire Class</p>
                    <p className="text-xs text-slate-500">General module for all students</p>
                  </button>
                  <button
                    onClick={() => setTargetType('personalized')}
                    className={cn(
                      'p-4 rounded-xl border-2 text-left transition-all',
                      targetType === 'personalized'
                        ? 'border-teal-500 bg-teal-50'
                        : 'border-slate-200 hover:border-teal-200'
                    )}
                  >
                    <User className="w-5 h-5 mb-2 text-teal-500" />
                    <p className="font-medium text-sm">Personalized</p>
                    <p className="text-xs text-slate-500">Tailored to specific student</p>
                  </button>
                </div>
              </div>

              {/* Student Selection (if personalized) */}
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
                          {student.name} ({student.studentId})
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  {targetStudent && (
                    <div className="p-3 bg-amber-50 rounded-lg border border-amber-200">
                      <p className="text-xs text-amber-700">
                        AI will analyze this student's performance to personalize content.
                      </p>
                    </div>
                  )}
                </div>
              )}

              {/* Topic */}
              <div className="space-y-2">
                <Label>Topic</Label>
                <Input
                  value={topic}
                  onChange={(e) => setTopic(e.target.value)}
                  placeholder="e.g., Force Vectors and Equilibrium"
                />
              </div>

              {/* Difficulty Level */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <Label>Difficulty Level</Label>
                  <Badge variant="secondary">
                    {difficultyLevel[0] === 1 && 'Beginner'}
                    {difficultyLevel[0] === 2 && 'Easy'}
                    {difficultyLevel[0] === 3 && 'Intermediate'}
                    {difficultyLevel[0] === 4 && 'Advanced'}
                    {difficultyLevel[0] === 5 && 'Expert'}
                  </Badge>
                </div>
                <Slider
                  value={difficultyLevel}
                  onValueChange={setDifficultyLevel}
                  min={1}
                  max={5}
                  step={1}
                />
                <div className="flex justify-between text-xs text-slate-400">
                  <span>Beginner</span>
                  <span>Expert</span>
                </div>
              </div>

              {/* Duration */}
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label className="flex items-center gap-2">
                    <Clock className="w-4 h-4" />
                    Estimated Duration
                  </Label>
                  <span className="text-sm font-medium">{estimatedDuration} min</span>
                </div>
                <Slider
                  value={[estimatedDuration]}
                  onValueChange={(v) => setEstimatedDuration(v[0])}
                  min={15}
                  max={120}
                  step={5}
                />
              </div>

              {/* Learning Objectives */}
              <div className="space-y-2">
                <Label className="flex items-center gap-2">
                  <Target className="w-4 h-4" />
                  Learning Objectives
                </Label>
                <Textarea
                  value={learningObjectives}
                  onChange={(e) => setLearningObjectives(e.target.value)}
                  placeholder="Enter learning objectives, one per line..."
                  rows={4}
                />
                <p className="text-xs text-slate-500">One objective per line</p>
              </div>

              {/* Content Options */}
              <div className="space-y-3">
                <Label>Content Options</Label>
                <div className="flex items-center justify-between p-3 bg-white rounded-lg border">
                  <div className="flex items-center gap-2">
                    <FunctionSquare className="w-4 h-4 text-indigo-500" />
                    <span className="text-sm">Include Equations</span>
                  </div>
                  <Switch checked={includeEquations} onCheckedChange={setIncludeEquations} />
                </div>
                <div className="flex items-center justify-between p-3 bg-white rounded-lg border">
                  <div className="flex items-center gap-2">
                    <ImageIcon className="w-4 h-4 text-teal-500" />
                    <span className="text-sm">Include Diagrams</span>
                  </div>
                  <Switch checked={includeDiagrams} onCheckedChange={setIncludeDiagrams} />
                </div>
              </div>

              {/* Generate Button */}
              <Button
                className="w-full gap-2 bg-indigo-600 hover:bg-indigo-700 h-12"
                onClick={handleGenerate}
                disabled={isGenerating || !selectedCourse || !topic}
              >
                {isGenerating ? (
                  <>
                    <Loader2 className="w-5 h-5 animate-spin" />
                    Generating with AI...
                  </>
                ) : (
                  <>
                    <Sparkles className="w-5 h-5" />
                    Generate Module
                  </>
                )}
              </Button>
            </TabsContent>

            <TabsContent value="edit" className="m-0 p-6">
              {generatedModule && (
                <div className="space-y-4">
                  <div className="p-4 bg-teal-50 rounded-xl border border-teal-200">
                    <div className="flex items-center gap-2 mb-2">
                      <CheckCircle className="w-5 h-5 text-teal-600" />
                      <span className="font-medium text-teal-800">AI Generation Complete</span>
                    </div>
                    <p className="text-sm text-teal-700">
                      Review and edit the content below before publishing.
                    </p>
                  </div>
                  
                  <div className="space-y-2">
                    <Label>Module Title</Label>
                    <Input value={generatedModule.title} readOnly />
                  </div>
                  
                  <div className="space-y-2">
                    <Label>Description</Label>
                    <Input value={generatedModule.description} readOnly />
                  </div>

                  <div className="flex gap-2">
                    <Badge variant="secondary" className="bg-indigo-100 text-indigo-700">
                      Difficulty: {generatedModule.aiMetadata?.difficultyLevel}/5
                    </Badge>
                    <Badge variant="secondary" className="bg-teal-100 text-teal-700">
                      {generatedModule.estimatedDuration} min
                    </Badge>
                  </div>
                </div>
              )}
            </TabsContent>
          </div>

          {/* Right Panel - Editor/Preview */}
          <div className="flex-1 bg-slate-100 p-6 overflow-auto">
            {activeTab === 'edit' && generatedModule ? (
              <div className="max-w-4xl mx-auto space-y-4">
                <div className="flex items-center justify-between">
                  <h2 className="text-lg font-semibold flex items-center gap-2">
                    <Edit3 className="w-5 h-5" />
                    Edit Content
                  </h2>
                  <p className="text-sm text-slate-500">
                    Edit directly or use the toolbar for formatting
                  </p>
                </div>
                <RichTextEditor content={editedContent} onChange={setEditedContent} />
              </div>
            ) : (
              <div className="h-full flex items-center justify-center">
                <div className="text-center space-y-4">
                  <div className="w-24 h-24 bg-indigo-100 rounded-full flex items-center justify-center mx-auto">
                    <Sparkles className="w-12 h-12 text-indigo-400" />
                  </div>
                  <div>
                    <h3 className="text-xl font-semibold text-slate-700">Ready to Generate</h3>
                    <p className="text-slate-500 max-w-md mt-2">
                      Configure your module settings on the left, then click "Generate Module" 
                      to create AI-powered learning content.
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
