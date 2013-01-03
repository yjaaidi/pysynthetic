#-*- coding: utf-8 -*-
#
# Created on Dec 17, 2012
#
# @author: Younes JAAIDI
#
# $Id$
#

from contracts import contract, new_contract
from synthetic.i_naming_convention import INamingConvention
from synthetic.naming_convention_camel_case import NamingConventionCamelCase
from synthetic.synthetic_member import SyntheticMember
from synthetic.synthetic_meta_data import SyntheticMetaData
import copy
import inspect

new_contract('INamingConvention', INamingConvention)
new_contract('SyntheticMember', SyntheticMember)

class SyntheticDecoratorFactory:

    @contract
    def syntheticMemberDecorator(self,
                                 memberName,
                                 defaultValue,
                                 contract,
                                 readOnly,
                                 getterName,
                                 setterName,
                                 privateMemberName):
        """
    :type memberName: str
    :type readOnly: bool
    :type getterName: str|None
    :type setterName: str|None
    :type privateMemberName: str|None
"""
        def decoratorFunction(cls):
            syntheticMember = SyntheticMember(memberName,
                                              defaultValue,
                                              contract,
                                              readOnly,
                                              getterName,
                                              setterName,
                                              privateMemberName)
        
            # Inserting this member at the beginning of the member list of synthesization data attribute
            # because decorators are called in reversed order.
            self._syntheticMetaData(cls).insertSyntheticMemberAtBegin(syntheticMember)
            
            self._updateClass(cls)
            return cls
        return decoratorFunction

    def syntheticConstructorDecorator(self):
        def functionWrapper(cls):            
            # This will be used later to tell the new constructor to consume parameters to initialize members.
            self._syntheticMetaData(cls).setConsumeArguments(True)
            
            self._updateClass(cls)
            return cls
        return functionWrapper
    
    def namingConventionDecorator(self, namingConvention):
        """
    :type namingConvention:INamingConvention
"""
        def decoratorFunction(cls):
            # Remove getters and setters with old naming convention.
            self._removeAccessorForMemberAll(cls)
            
            # Set new naming convention.
            self._syntheticMetaData(cls).setNamingConvention(namingConvention)
            
            # Update constructor and recreate getters and setters.
            self._updateClass(cls)
            return cls
        return decoratorFunction

    def _syntheticMetaData(self, cls):
        # SyntheticMetaData does not exist...
        syntheticMetaDataName = '__syntheticMetaData__'
        if not hasattr(cls, syntheticMetaDataName):
            # ...we create it.
            originalConstructor = getattr(cls, '__init__', None)
            
            # List of existing methods (Python2: ismethod, Python3: isfunction).
            originalMethodList = inspect.getmembers(cls,
                                                    predicate = lambda m: inspect.ismethod(m) or inspect.isfunction(m))
            originalMethodNameList = [method[0] for method in originalMethodList]
            
            # Making the synthetic meta data.
            syntheticMetaData = SyntheticMetaData(originalConstructor = originalConstructor,
                                                  originalMethodNameList = originalMethodNameList,
                                                  namingConvention = NamingConventionCamelCase())
            setattr(cls, syntheticMetaDataName, syntheticMetaData)
        return getattr(cls, syntheticMetaDataName)

    def _updateClass(self, cls):
        """We overwrite constructor, getters and setters every time because the constructor might have to consume all
members even if their decorator is below the "synthesizeConstructor" decorator and it also might need to update
the getters and setters because the naming convention has changed.
"""
        self._overrideConstructor(cls)
        for syntheticMember in self._syntheticMetaData(cls).syntheticMemberList():
            self._makeGetter(cls, syntheticMember)
            self._makeSetter(cls, syntheticMember)

    def _overrideConstructor(self, cls):
        # Retrieving synthesized member list and original init method.
        syntheticMetaData = self._syntheticMetaData(cls)
        originalConstructor = syntheticMetaData.originalConstructor()
        syntheticMemberList = syntheticMetaData.syntheticMemberList()
        doesConsumeArguments = syntheticMetaData.doesConsumeArguments()
        
        def init(instance, *args, **kwargs):
            # Original constructor's expected args.
            originalConstructorExpectedArgList = []
            doesExpectVariadicArgs = False
            doesExpectKeywordedArgs = False
            
            if inspect.isfunction(originalConstructor) or inspect.ismethod(originalConstructor):
                argSpec = inspect.getargspec(originalConstructor)
                # originalConstructorExpectedArgList = expected args - self.
                originalConstructorExpectedArgList = argSpec.args[1:]
                doesExpectVariadicArgs = (argSpec.varargs is not None)
                doesExpectKeywordedArgs = (argSpec.keywords is not None)
                   
            # Merge original constructor's args specification with member list and make an args dict.
            positionalArgumentKeyValueList = self._positionalArgumentKeyValueList(originalConstructorExpectedArgList,
                                                                                syntheticMemberList,
                                                                                args)

            # Set members values.
            for syntheticMember in syntheticMemberList:
                memberName = syntheticMember.memberName()
                
                # Default value.
                value = syntheticMember.defaultValue()

                # Constructor is synthesized.
                if doesConsumeArguments:
                    value = self._consumeArgument(memberName,
                                                  positionalArgumentKeyValueList,
                                                  kwargs,
                                                  value)

                # Initalizing member with a value.
                setattr(instance,
                        syntheticMember.privateMemberName(),
                        value)

            # Remove superfluous arguments that have been used for synthesization but are not expected by constructor.
            args, kwargs = self._filterArgsAndKwargs(originalConstructorExpectedArgList,
                                                     doesExpectVariadicArgs,
                                                     doesExpectKeywordedArgs,
                                                     syntheticMemberList,
                                                     positionalArgumentKeyValueList,
                                                     kwargs)
            # Call original constructor.
            if originalConstructor is not None:
                originalConstructor(instance, *args, **kwargs)
        
        # Setting init method.
        cls.__init__ = init

    @contract
    def _positionalArgumentKeyValueList(self,
                                        originalConstructorExpectedArgList,
                                        syntheticMemberList,
                                        argTuple):
        """Transforms args tuple to a dictionary mapping argument names to values using original constructor
positional args specification, then it adds synthesized members at the end if they are not already present.
    :type syntheticMemberList: list(SyntheticMember)
    :type argTuple: tuple
"""
        
        # First, the list of expected arguments is set to original constructor's arg spec. 
        expectedArgList = copy.copy(originalConstructorExpectedArgList)
        
        # ... then we append members that are not already present.
        for syntheticMember in syntheticMemberList:
            memberName = syntheticMember.memberName()
            if memberName not in expectedArgList:
                expectedArgList.append(memberName)
        
        # Makes a list of tuples (argumentName, argumentValue) with each element of each list (expectedArgList, argTuple)
        # until the shortest list's end is reached.
        positionalArgumentKeyValueList = list(zip(expectedArgList, argTuple))
        
        # Add remanining arguments (those that are not expected by the original constructor).
        for argumentValue in argTuple[len(positionalArgumentKeyValueList):]:
            positionalArgumentKeyValueList.append((None, argumentValue))

        return positionalArgumentKeyValueList

    @contract
    def _consumeArgument(self,
                         memberName,
                         positionalArgumentKeyValueList,
                         kwargs,
                         defaultValue):
        """Returns member's value from kwargs if found or from positionalArgumentKeyValueList if found
or default value otherwise.
    :type memberName: str
    :type positionalArgumentKeyValueList: list(tuple)
    :type kwargs: dict(str:*)
"""
        # Warning: we use this dict to simplify the usage of the key-value tuple list but be aware that this will
        # merge superfluous arguments as they have the same key : None.
        positionalArgumentDict = dict(positionalArgumentKeyValueList)
     
        if memberName in kwargs:
            return kwargs[memberName]

        if memberName in positionalArgumentDict:
            return positionalArgumentDict[memberName]

        return defaultValue

    @contract
    def _filterArgsAndKwargs(self,
                           originalConstructorExpectedArgList,
                           doesExpectVariadicArgs,
                           doesExpectKeywordedArgs,
                           syntheticMemberList,
                           positionalArgumentKeyValueList,
                           keywordedArgDict):
        """Returns a tuple with variadic args and keyworded args after removing arguments that have been used to
synthesize members and that are not expected by the original constructor.
If original constructor accepts variadic args, all variadic args are forwarded.
If original constructor accepts keyworded args, all keyworded args are forwarded.
    :type originalConstructorExpectedArgList: list(str)
    :type doesExpectVariadicArgs: bool
    :type doesExpectKeywordedArgs: bool
    :type syntheticMemberList: list(SyntheticMember)
    :type positionalArgumentKeyValueList: list(tuple)
    :type keywordedArgDict: dict(str:*)
"""
        
        # List is initialized with all variadic arguments.
        positionalArgumentKeyValueList = copy.copy(positionalArgumentKeyValueList)
        
        # Warning: we use this dict to simplify the usage of the key-value tuple list but be aware that this will
        # merge superfluous arguments as they have the same key : None.
        positionalArgumentDict = dict(positionalArgumentKeyValueList)
        
        # Dict is initialized with all keyworded arguments.
        keywordedArgDict = keywordedArgDict.copy()
        
        for syntheticMember in syntheticMemberList:
            argumentName = syntheticMember.memberName()
            
            # Argument is expected by the original constructor.
            if argumentName in originalConstructorExpectedArgList:
                continue

            # We filter args only if original constructor does not expected variadic args. 
            if not doesExpectVariadicArgs and argumentName in positionalArgumentDict:
                positionalArgumentKeyValueList = list(filter(lambda pair: pair[0] != argumentName,
                                                             positionalArgumentKeyValueList))

            # We filter args only if original constructor does not expected keyworded args. 
            if not doesExpectKeywordedArgs and argumentName in keywordedArgDict:
                del keywordedArgDict[argumentName]

        positionalArgumentTuple = tuple([value for _, value in positionalArgumentKeyValueList])
        return positionalArgumentTuple, keywordedArgDict

    def _removeAccessorForMemberAll(self, cls):
        for syntheticMember in self._syntheticMetaData(cls).syntheticMemberList():
            self._removeAccessor(cls, self._getterName(cls, syntheticMember))
            self._removeAccessor(cls, self._setterName(cls, syntheticMember))

    def _makeGetter(self, cls, syntheticMember):
        def getter(instance):
            return getattr(instance, syntheticMember.privateMemberName())

        self._addAccessor(cls, self._getterName(cls, syntheticMember), getter)
    
    def _makeSetter(self, cls, syntheticMember):
        # No setter if read only member.
        if syntheticMember.isReadOnly():
            return
        
        def setter(instance, value):
            setattr(instance, syntheticMember.privateMemberName(), value)

        self._addAccessor(cls, self._setterName(cls, syntheticMember), setter)

    def _addAccessor(self, cls, accessorName, accessor):
        # Don't synthesize accessor if it is overriden by the user.
        if accessorName in self._syntheticMetaData(cls).originalMethodNameList():
            return
        setattr(cls, accessorName, accessor)
    
    def _removeAccessor(self, cls, accessorName):
        # Don't remove accessor if it is overriden by the user.
        if accessorName in self._syntheticMetaData(cls).originalMethodNameList():
            return  
        delattr(cls, accessorName)

    def _getterName(self, cls, syntheticMember):
        getterName = syntheticMember.getterName()
        if getterName is None:
            getterName = self._syntheticMetaData(cls).namingConvention().getterName(syntheticMember.memberName())
        return getterName
    
    def _setterName(self, cls, syntheticMember):
        setterName = syntheticMember.setterName()
        if setterName is None:
            setterName = self._syntheticMetaData(cls).namingConvention().setterName(syntheticMember.memberName())
        return setterName
